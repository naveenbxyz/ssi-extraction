import { startTransition, useDeferredValue, useEffect, useState, type ReactNode } from "react";
import {
  Bot,
  Database,
  FileJson,
  FileSearch,
  HeartPulse,
  MessageSquare,
  RefreshCcw,
  Search,
  ShieldCheck,
  Sparkles,
  TableProperties,
  Upload,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { fetchJson, toQueryString } from "@/lib/api";
import { cn } from "@/lib/utils";

type Workflow = "ssi" | "isda";
type SsiViewName = "standard" | "us" | "cash";

type ConfigPaths = {
  llmConfigPath: string;
  isdaConfigPath: string;
  ssiDbPath: string;
  isdaDbPath: string;
};

type BootstrapResponse = {
  defaults: {
    llm_config_path: string;
    isda_config_path: string;
    ssi_db_path: string;
    isda_db_path: string;
  };
  llm_config: Record<string, unknown> | null;
  isda_config_summary: {
    canonical_field_count: number;
    field_alias_count: number;
  };
  ssi_summary: Record<string, number>;
  isda_summary: Record<string, number>;
};

type SsiLatest = {
  metadata: Record<string, unknown> | null;
  structured: SsiStructured | null;
  raw_pages: RawPage[] | null;
};

type SsiStructured = {
  records: RowData[];
  us_securities_settlement: RowData[];
  cash_settlement: RowData[];
  notes: string[];
};

type RawPage = {
  page_number: number;
  text: string;
  tables: {
    table_index: number;
    header: string[];
    rows: string[][];
  }[];
};

type RowData = Record<string, unknown>;

type IsdaDocumentSummary = {
  doc_id: number;
  country_key: string;
  country: string;
  jurisdiction: string;
  source_file: string;
  uploaded_at: string;
  summary: string;
};

type IsdaDocumentContext = {
  doc_id: number;
  country_key: string;
  country: string;
  jurisdiction: string;
  source_file: string;
  uploaded_at: string;
  summary: string;
  extraction_json: Record<string, unknown>;
  raw_docx_payload: Record<string, unknown>;
};

type IsdaStructuredPayload = {
  country?: string;
  jurisdiction?: string;
  summary?: string;
  normalized_fields?: RowData[];
  additional_fields?: RowData[];
  notes?: string[];
};

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
};

type AlertState = {
  type: "success" | "error";
  message: string;
} | null;

const emptySsiLatest: SsiLatest = {
  metadata: null,
  structured: null,
  raw_pages: null,
};

export default function App() {
  const [workflow, setWorkflow] = useState<Workflow>("ssi");
  const [config, setConfig] = useState<ConfigPaths>({
    llmConfigPath: "config/llm_config.json",
    isdaConfigPath: "config/isda_extraction_config.json",
    ssiDbPath: "data/ssi.sqlite",
    isdaDbPath: "data/isda_netting.sqlite",
  });
  const [bootstrap, setBootstrap] = useState<BootstrapResponse | null>(null);
  const [loadingBootstrap, setLoadingBootstrap] = useState(true);
  const [alert, setAlert] = useState<AlertState>(null);

  const [ssiSummary, setSsiSummary] = useState<Record<string, number>>({});
  const [ssiLatest, setSsiLatest] = useState<SsiLatest>(emptySsiLatest);
  const [ssiUploadFile, setSsiUploadFile] = useState<File | null>(null);
  const [ssiRefreshDbOnUpload, setSsiRefreshDbOnUpload] = useState(true);
  const [ssiExtracting, setSsiExtracting] = useState(false);
  const [ssiLatestSearch, setSsiLatestSearch] = useState("");
  const deferredSsiLatestSearch = useDeferredValue(ssiLatestSearch);
  const [ssiViewName, setSsiViewName] = useState<SsiViewName>("standard");
  const [ssiDbSearch, setSsiDbSearch] = useState("");
  const deferredSsiDbSearch = useDeferredValue(ssiDbSearch);
  const [ssiDbRows, setSsiDbRows] = useState<RowData[]>([]);
  const [ssiSql, setSsiSql] = useState("SELECT * FROM standard_ssi LIMIT 50");
  const [ssiSqlRows, setSsiSqlRows] = useState<RowData[]>([]);
  const [ssiChatQuestion, setSsiChatQuestion] = useState("");
  const [ssiChatLoading, setSsiChatLoading] = useState(false);
  const [ssiChatHistory, setSsiChatHistory] = useState<ChatMessage[]>([]);

  const [isdaSummary, setIsdaSummary] = useState<Record<string, number>>({});
  const [isdaUploadFile, setIsdaUploadFile] = useState<File | null>(null);
  const [isdaCountryOverride, setIsdaCountryOverride] = useState("");
  const [isdaExtracting, setIsdaExtracting] = useState(false);
  const [isdaLatest, setIsdaLatest] = useState<{
    country_key: string;
    structured: IsdaStructuredPayload;
    raw_payload: Record<string, unknown>;
  } | null>(null);
  const [isdaDocuments, setIsdaDocuments] = useState<IsdaDocumentSummary[]>([]);
  const [selectedIsdaDocId, setSelectedIsdaDocId] = useState<number | null>(null);
  const [isdaContext, setIsdaContext] = useState<IsdaDocumentContext | null>(null);
  const [isdaFieldSearch, setIsdaFieldSearch] = useState("");
  const deferredIsdaFieldSearch = useDeferredValue(isdaFieldSearch);
  const [isdaFieldRows, setIsdaFieldRows] = useState<RowData[]>([]);
  const [isdaSql, setIsdaSql] = useState("SELECT * FROM isda_fields LIMIT 50");
  const [isdaSqlRows, setIsdaSqlRows] = useState<RowData[]>([]);
  const [isdaChatQuestion, setIsdaChatQuestion] = useState("");
  const [isdaChatLoading, setIsdaChatLoading] = useState(false);
  const [isdaChatHistory, setIsdaChatHistory] = useState<ChatMessage[]>([]);

  async function reloadBootstrap(nextConfig = config) {
    setLoadingBootstrap(true);
    try {
      const query = toQueryString({
        llm_config_path: nextConfig.llmConfigPath,
        isda_config_path: nextConfig.isdaConfigPath,
        ssi_db_path: nextConfig.ssiDbPath,
        isda_db_path: nextConfig.isdaDbPath,
      });
      const payload = await fetchJson<BootstrapResponse>(`/api/bootstrap?${query}`);

      startTransition(() => {
        setBootstrap(payload);
        setSsiSummary(payload.ssi_summary);
        setIsdaSummary(payload.isda_summary);
      });
    } catch (error) {
      setAlert({ type: "error", message: errorMessage(error) });
    } finally {
      setLoadingBootstrap(false);
    }
  }

  async function refreshSsiLatest(nextConfig = config) {
    try {
      const query = toQueryString({ db_path: nextConfig.ssiDbPath });
      const payload = await fetchJson<SsiLatest>(`/api/ssi/latest?${query}`);
      startTransition(() => setSsiLatest(payload));
    } catch (error) {
      setAlert({ type: "error", message: errorMessage(error) });
    }
  }

  async function refreshSsiView(nextView = ssiViewName, nextSearch = deferredSsiDbSearch, nextConfig = config) {
    try {
      const query = toQueryString({
        db_path: nextConfig.ssiDbPath,
        search_term: nextSearch,
      });
      const payload = await fetchJson<{ rows: RowData[] }>(`/api/ssi/views/${nextView}?${query}`);
      startTransition(() => setSsiDbRows(payload.rows));
    } catch (error) {
      setAlert({ type: "error", message: errorMessage(error) });
    }
  }

  async function refreshIsdaDocuments(nextConfig = config) {
    try {
      const query = toQueryString({ db_path: nextConfig.isdaDbPath });
      const payload = await fetchJson<{ documents: IsdaDocumentSummary[] }>(`/api/isda/documents?${query}`);

      startTransition(() => {
        setIsdaDocuments(payload.documents);
        if (payload.documents.length === 0) {
          setSelectedIsdaDocId(null);
        } else if (
          selectedIsdaDocId === null ||
          !payload.documents.some((document) => document.doc_id === selectedIsdaDocId)
        ) {
          setSelectedIsdaDocId(payload.documents[0].doc_id);
        }
      });
    } catch (error) {
      setAlert({ type: "error", message: errorMessage(error) });
    }
  }

  async function refreshIsdaContext(docId: number, nextConfig = config) {
    try {
      const query = toQueryString({ db_path: nextConfig.isdaDbPath });
      const payload = await fetchJson<IsdaDocumentContext>(`/api/isda/documents/${docId}?${query}`);
      startTransition(() => setIsdaContext(payload));
    } catch (error) {
      setAlert({ type: "error", message: errorMessage(error) });
    }
  }

  async function refreshIsdaFields(docId: number, nextSearch = deferredIsdaFieldSearch, nextConfig = config) {
    try {
      const query = toQueryString({
        db_path: nextConfig.isdaDbPath,
        search_term: nextSearch,
      });
      const payload = await fetchJson<{ rows: RowData[] }>(`/api/isda/documents/${docId}/fields?${query}`);
      startTransition(() => setIsdaFieldRows(payload.rows));
    } catch (error) {
      setAlert({ type: "error", message: errorMessage(error) });
    }
  }

  useEffect(() => {
    void reloadBootstrap();
    void refreshSsiLatest();
    void refreshSsiView();
    void refreshIsdaDocuments();
  }, []);

  useEffect(() => {
    void refreshSsiView(ssiViewName, deferredSsiDbSearch);
  }, [ssiViewName, deferredSsiDbSearch]);

  useEffect(() => {
    if (selectedIsdaDocId === null) {
      setIsdaContext(null);
      setIsdaFieldRows([]);
      return;
    }
    setIsdaChatHistory([]);
    void refreshIsdaContext(selectedIsdaDocId);
    void refreshIsdaFields(selectedIsdaDocId, deferredIsdaFieldSearch);
  }, [selectedIsdaDocId]);

  useEffect(() => {
    if (selectedIsdaDocId === null) {
      return;
    }
    void refreshIsdaFields(selectedIsdaDocId, deferredIsdaFieldSearch);
  }, [deferredIsdaFieldSearch]);

  const filteredStandard = filterRows(ssiLatest.structured?.records ?? [], deferredSsiLatestSearch);
  const filteredUs = filterRows(ssiLatest.structured?.us_securities_settlement ?? [], deferredSsiLatestSearch);
  const filteredCash = filterRows(ssiLatest.structured?.cash_settlement ?? [], deferredSsiLatestSearch);

  async function handleSsiExtract() {
    if (!ssiUploadFile) {
      setAlert({ type: "error", message: "Select a PDF before running SSI extraction." });
      return;
    }

    setSsiExtracting(true);
    setAlert(null);

    try {
      const formData = new FormData();
      formData.set("file", ssiUploadFile);
      formData.set("llm_config_path", config.llmConfigPath);
      formData.set("db_path", config.ssiDbPath);
      formData.set("refresh_db_on_upload", String(ssiRefreshDbOnUpload));

      const payload = await fetchJson<{
        stats: Record<string, number>;
        latest: SsiLatest;
      }>("/api/ssi/extract", {
        method: "POST",
        body: formData,
      });

      startTransition(() => {
        setSsiLatest(payload.latest);
        setSsiChatHistory([]);
      });

      await reloadBootstrap();
      await refreshSsiView();
      setAlert({
        type: "success",
        message: `SSI extraction completed. ${payload.stats.rows_written ?? 0} rows persisted.`,
      });
    } catch (error) {
      setAlert({ type: "error", message: errorMessage(error) });
    } finally {
      setSsiExtracting(false);
    }
  }

  async function handleIsdaExtract() {
    if (!isdaUploadFile) {
      setAlert({ type: "error", message: "Select a DOCX file before running ISDA extraction." });
      return;
    }

    setIsdaExtracting(true);
    setAlert(null);

    try {
      const formData = new FormData();
      formData.set("file", isdaUploadFile);
      formData.set("llm_config_path", config.llmConfigPath);
      formData.set("isda_config_path", config.isdaConfigPath);
      formData.set("db_path", config.isdaDbPath);
      formData.set("country_override", isdaCountryOverride);

      const payload = await fetchJson<{
        stats: Record<string, unknown>;
        document: {
          country_key: string;
          structured: IsdaStructuredPayload;
          raw_payload: Record<string, unknown>;
        };
      }>("/api/isda/extract", {
        method: "POST",
        body: formData,
      });

      startTransition(() => {
        setIsdaLatest(payload.document);
        setIsdaChatHistory([]);
      });

      await reloadBootstrap();
      await refreshIsdaDocuments();
      setAlert({
        type: "success",
        message: `ISDA extraction completed for ${String(payload.document.country_key)}.`,
      });
    } catch (error) {
      setAlert({ type: "error", message: errorMessage(error) });
    } finally {
      setIsdaExtracting(false);
    }
  }

  async function handleSsiSql() {
    try {
      const payload = await fetchJson<{ rows: RowData[] }>("/api/ssi/query", {
        method: "POST",
        body: JSON.stringify({
          db_path: config.ssiDbPath,
          query: ssiSql,
        }),
      });
      setSsiSqlRows(payload.rows);
      setAlert({ type: "success", message: `SSI SQL returned ${payload.rows.length} rows.` });
    } catch (error) {
      setAlert({ type: "error", message: errorMessage(error) });
    }
  }

  async function handleIsdaSql() {
    try {
      const payload = await fetchJson<{ rows: RowData[] }>("/api/isda/query", {
        method: "POST",
        body: JSON.stringify({
          db_path: config.isdaDbPath,
          query: isdaSql,
        }),
      });
      setIsdaSqlRows(payload.rows);
      setAlert({ type: "success", message: `ISDA SQL returned ${payload.rows.length} rows.` });
    } catch (error) {
      setAlert({ type: "error", message: errorMessage(error) });
    }
  }

  async function handleSsiChat() {
    if (!ssiChatQuestion.trim()) {
      return;
    }

    const question = ssiChatQuestion.trim();
    setSsiChatLoading(true);
    setSsiChatQuestion("");
    setSsiChatHistory((prev) => [...prev, { role: "user", content: question }]);

    try {
      const payload = await fetchJson<{ answer: string }>("/api/ssi/chat", {
        method: "POST",
        body: JSON.stringify({
          llm_config_path: config.llmConfigPath,
          db_path: config.ssiDbPath,
          question,
          extraction_payload: ssiLatest.structured,
        }),
      });
      setSsiChatHistory((prev) => [...prev, { role: "assistant", content: payload.answer }]);
    } catch (error) {
      setSsiChatHistory((prev) => [...prev, { role: "assistant", content: errorMessage(error) }]);
    } finally {
      setSsiChatLoading(false);
    }
  }

  async function handleIsdaChat() {
    if (!isdaChatQuestion.trim() || selectedIsdaDocId === null) {
      return;
    }

    const question = isdaChatQuestion.trim();
    setIsdaChatLoading(true);
    setIsdaChatQuestion("");
    setIsdaChatHistory((prev) => [...prev, { role: "user", content: question }]);

    try {
      const payload = await fetchJson<{ answer: string }>("/api/isda/chat", {
        method: "POST",
        body: JSON.stringify({
          llm_config_path: config.llmConfigPath,
          isda_config_path: config.isdaConfigPath,
          db_path: config.isdaDbPath,
          doc_id: selectedIsdaDocId,
          question,
        }),
      });
      setIsdaChatHistory((prev) => [...prev, { role: "assistant", content: payload.answer }]);
    } catch (error) {
      setIsdaChatHistory((prev) => [...prev, { role: "assistant", content: errorMessage(error) }]);
    } finally {
      setIsdaChatLoading(false);
    }
  }

  function handleDownloadJson(filename: string, data: unknown) {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="mx-auto min-h-screen max-w-[1600px] px-4 py-6 md:px-6 lg:px-10">
      <header className="relative overflow-hidden rounded-[2rem] border border-white/70 bg-[radial-gradient(circle_at_top_left,rgba(255,255,255,0.95),rgba(255,245,236,0.85)_45%,rgba(228,237,240,0.92)_100%)] p-6 shadow-panel md:p-10">
        <div className="absolute inset-0 bg-grid bg-[length:34px_34px] opacity-35" />
        <div className="absolute -right-10 top-6 h-32 w-32 rounded-full bg-[hsl(var(--accent)/0.18)] blur-3xl" />
        <div className="absolute bottom-0 left-1/3 h-28 w-28 rounded-full bg-[hsl(var(--accent-2)/0.15)] blur-3xl" />
        <div className="relative flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
          <div className="max-w-3xl">
            <Badge>Control Center</Badge>
            <h1 className="mt-4 max-w-2xl font-display text-4xl leading-tight text-balance md:text-6xl">
              SSI and ISDA extraction with an actual application shell.
            </h1>
            <p className="mt-4 max-w-2xl text-sm leading-6 text-muted md:text-base">
              The Streamlit interface is replaced by a FastAPI backend and a React frontend designed for uploads,
              investigation, auditability, and LLM-assisted review without crowding everything into one page.
            </p>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <MiniStat
              icon={<HeartPulse className="h-4 w-4" />}
              label="API"
              value={loadingBootstrap ? "Loading" : "Healthy"}
            />
            <MiniStat
              icon={<TableProperties className="h-4 w-4" />}
              label="SSI Rows"
              value={String(ssiSummary.total_rows ?? 0)}
            />
            <MiniStat
              icon={<FileJson className="h-4 w-4" />}
              label="ISDA Docs"
              value={String(isdaSummary.document_count ?? 0)}
            />
          </div>
        </div>
      </header>

      <div className="mt-6 grid gap-6 xl:grid-cols-[320px_minmax(0,1fr)]">
        <aside className="space-y-6">
          <Card className="p-5">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-muted">Workspace</p>
                <h2 className="mt-1 font-display text-2xl">Runtime paths</h2>
              </div>
              <ShieldCheck className="h-5 w-5 text-[hsl(var(--accent-2))]" />
            </div>

            <div className="mt-5 space-y-4">
              <Field label="LLM config">
                <Input
                  value={config.llmConfigPath}
                  onChange={(event) => setConfig((prev) => ({ ...prev, llmConfigPath: event.target.value }))}
                />
              </Field>
              <Field label="ISDA config">
                <Input
                  value={config.isdaConfigPath}
                  onChange={(event) => setConfig((prev) => ({ ...prev, isdaConfigPath: event.target.value }))}
                />
              </Field>
              <Field label="SSI database">
                <Input
                  value={config.ssiDbPath}
                  onChange={(event) => setConfig((prev) => ({ ...prev, ssiDbPath: event.target.value }))}
                />
              </Field>
              <Field label="ISDA database">
                <Input
                  value={config.isdaDbPath}
                  onChange={(event) => setConfig((prev) => ({ ...prev, isdaDbPath: event.target.value }))}
                />
              </Field>
            </div>

            <div className="mt-5 flex flex-wrap gap-3">
              <Button
                variant="secondary"
                onClick={async () => {
                  setAlert(null);
                  await reloadBootstrap();
                  await refreshSsiLatest();
                  await refreshSsiView(ssiViewName, deferredSsiDbSearch);
                  await refreshIsdaDocuments();
                }}
              >
                <RefreshCcw className="mr-2 h-4 w-4" />
                Reload state
              </Button>
            </div>

            {bootstrap?.llm_config ? (
              <div className="mt-5 rounded-3xl bg-[hsl(var(--ink)/0.04)] p-4">
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-muted">LLM config</p>
                <pre className="mt-2 overflow-auto text-xs leading-6 text-ink">
                  {JSON.stringify(bootstrap.llm_config, null, 2)}
                </pre>
              </div>
            ) : null}
          </Card>

          <Card className="overflow-hidden">
            <div className="border-b border-line px-5 py-4">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-muted">Workflows</p>
              <h2 className="mt-1 font-display text-2xl">Navigation</h2>
            </div>
            <div className="space-y-2 p-3">
              <WorkflowButton
                active={workflow === "ssi"}
                icon={<Database className="h-4 w-4" />}
                title="SSI extraction"
                description="PDF intake, normalized tables, and investigation tools"
                onClick={() => setWorkflow("ssi")}
              />
              <WorkflowButton
                active={workflow === "isda"}
                icon={<FileSearch className="h-4 w-4" />}
                title="ISDA netting review"
                description="DOCX extraction, document-level fields, and chat"
                onClick={() => setWorkflow("isda")}
              />
            </div>
          </Card>

          {alert ? (
            <Card
              className={cn(
                "p-4",
                alert.type === "error"
                  ? "border-[hsl(var(--danger)/0.35)] bg-[hsl(var(--danger)/0.05)]"
                  : "border-[hsl(var(--success)/0.3)] bg-[hsl(var(--success)/0.08)]",
              )}
            >
              <p className="text-sm font-semibold">{alert.type === "error" ? "Request failed" : "Latest update"}</p>
              <p className="mt-1 text-sm text-muted">{alert.message}</p>
            </Card>
          ) : null}
        </aside>

        <main className="space-y-6">
          {workflow === "ssi" ? (
            <>
              <MetricGrid
                items={[
                  { label: "Runs", value: String(ssiSummary.runs ?? 0), icon: <Sparkles className="h-4 w-4" /> },
                  { label: "Total rows", value: String(ssiSummary.total_rows ?? 0), icon: <Database className="h-4 w-4" /> },
                  { label: "Standard", value: String(ssiSummary.standard_rows ?? 0), icon: <TableProperties className="h-4 w-4" /> },
                  { label: "US SSI", value: String(ssiSummary.us_rows ?? 0), icon: <TableProperties className="h-4 w-4" /> },
                  { label: "Cash", value: String(ssiSummary.cash_rows ?? 0), icon: <TableProperties className="h-4 w-4" /> },
                ]}
              />

              <div className="grid gap-6 2xl:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)]">
                <Card className="p-5 md:p-6">
                  <SectionHeader
                    eyebrow="SSI upload"
                    title="Run PDF extraction"
                    description="Send a PDF to the FastAPI backend, persist normalized rows to SQLite, and keep the raw page payload for review."
                  />
                  <div className="mt-5 grid gap-4 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
                    <Field label="PDF file">
                      <Input
                        type="file"
                        accept=".pdf"
                        onChange={(event) => setSsiUploadFile(event.target.files?.[0] ?? null)}
                      />
                    </Field>
                    <label className="flex items-center gap-3 rounded-2xl border border-line bg-white px-4 py-3 text-sm text-ink">
                      <input
                        checked={ssiRefreshDbOnUpload}
                        onChange={(event) => setSsiRefreshDbOnUpload(event.target.checked)}
                        type="checkbox"
                      />
                      Refresh DB on upload
                    </label>
                  </div>
                  <div className="mt-5 flex flex-wrap gap-3">
                    <Button onClick={() => void handleSsiExtract()} disabled={ssiExtracting}>
                      <Upload className="mr-2 h-4 w-4" />
                      {ssiExtracting ? "Extracting..." : "Run SSI extraction"}
                    </Button>
                    {ssiLatest.structured ? (
                      <Button variant="ghost" onClick={() => handleDownloadJson("ssi_extraction.json", ssiLatest.structured)}>
                        Download JSON
                      </Button>
                    ) : null}
                  </div>
                </Card>

                <Card className="p-5 md:p-6">
                  <SectionHeader
                    eyebrow="Latest run"
                    title="Extraction snapshot"
                    description="Review the in-memory result returned by the API without needing to query SQLite first."
                  />
                  <div className="mt-5 grid gap-3 sm:grid-cols-2">
                    <MiniStat label="Pages" value={String(ssiLatest.raw_pages?.length ?? 0)} icon={<FileSearch className="h-4 w-4" />} />
                    <MiniStat
                      label="Standard rows"
                      value={String(ssiLatest.structured?.records.length ?? 0)}
                      icon={<TableProperties className="h-4 w-4" />}
                    />
                    <MiniStat
                      label="US rows"
                      value={String(ssiLatest.structured?.us_securities_settlement.length ?? 0)}
                      icon={<TableProperties className="h-4 w-4" />}
                    />
                    <MiniStat
                      label="Cash rows"
                      value={String(ssiLatest.structured?.cash_settlement.length ?? 0)}
                      icon={<TableProperties className="h-4 w-4" />}
                    />
                  </div>
                  {ssiLatest.metadata ? (
                    <div className="mt-5 rounded-3xl bg-[hsl(var(--ink)/0.04)] p-4 text-sm leading-6 text-muted">
                      <p className="font-semibold text-ink">Run metadata</p>
                      <pre className="mt-2 overflow-auto text-xs leading-6">{JSON.stringify(ssiLatest.metadata, null, 2)}</pre>
                    </div>
                  ) : (
                    <EmptyState title="No extraction yet" copy="Upload an SSI PDF to populate the latest extraction panel." />
                  )}
                </Card>
              </div>

              <Card className="p-5 md:p-6">
                <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
                  <SectionHeader
                    eyebrow="Latest extraction"
                    title="Review extracted values"
                    description="Client-side filtering is applied here so you can inspect the latest API response immediately."
                  />
                  <div className="w-full max-w-sm">
                    <Field label="Search extracted values">
                      <div className="relative">
                        <Search className="pointer-events-none absolute left-4 top-3.5 h-4 w-4 text-muted" />
                        <Input className="pl-11" value={ssiLatestSearch} onChange={(event) => setSsiLatestSearch(event.target.value)} />
                      </div>
                    </Field>
                  </div>
                </div>

                <div className="mt-5 space-y-4">
                  <TabbedTables
                    tabs={[
                      { id: "standard", label: `Standard (${filteredStandard.length})`, content: <DataTable rows={filteredStandard} /> },
                      { id: "us", label: `US (${filteredUs.length})`, content: <DataTable rows={filteredUs} /> },
                      { id: "cash", label: `Cash (${filteredCash.length})`, content: <DataTable rows={filteredCash} /> },
                      {
                        id: "raw",
                        label: `Raw pages (${ssiLatest.raw_pages?.length ?? 0})`,
                        content: <RawPagesPanel pages={ssiLatest.raw_pages ?? []} />,
                      },
                    ]}
                  />
                </div>
              </Card>

              <div className="grid gap-6 2xl:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]">
                <Card className="p-5 md:p-6">
                  <SectionHeader
                    eyebrow="SQLite views"
                    title="Query normalized SSI tables"
                    description="Switch across standard, US, and cash settlement views with server-side search over SQLite."
                  />
                  <div className="mt-5 flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                    <div className="flex flex-wrap gap-2">
                      {(["standard", "us", "cash"] as SsiViewName[]).map((name) => (
                        <Button
                          key={name}
                          variant={ssiViewName === name ? "secondary" : "ghost"}
                          className="capitalize"
                          onClick={() => setSsiViewName(name)}
                        >
                          {name}
                        </Button>
                      ))}
                    </div>
                    <div className="w-full max-w-sm">
                      <Field label="Search SQLite rows">
                        <Input value={ssiDbSearch} onChange={(event) => setSsiDbSearch(event.target.value)} />
                      </Field>
                    </div>
                  </div>
                  <div className="mt-5">
                    <DataTable rows={ssiDbRows} />
                  </div>
                </Card>

                <Card className="p-5 md:p-6">
                  <SectionHeader
                    eyebrow="Read-only SQL"
                    title="Run custom SSI queries"
                    description="Only SELECT and WITH queries are accepted by the backend."
                  />
                  <div className="mt-5 space-y-4">
                    <Textarea value={ssiSql} onChange={(event) => setSsiSql(event.target.value)} />
                    <Button onClick={() => void handleSsiSql()}>Run SSI SQL</Button>
                    <DataTable rows={ssiSqlRows} />
                  </div>
                </Card>
              </div>

              <Card className="p-5 md:p-6">
                <SectionHeader
                  eyebrow="JSON chat"
                  title="Ask questions about the latest SSI extraction"
                  description="The chat endpoint uses the full extraction payload rather than the normalized row views."
                />
                <ChatPanel
                  history={ssiChatHistory}
                  value={ssiChatQuestion}
                  onChange={setSsiChatQuestion}
                  onSubmit={() => void handleSsiChat()}
                  loading={ssiChatLoading}
                  placeholder="Ask about account numbers, markets, BICs, or extracted notes."
                  onClear={() => setSsiChatHistory([])}
                />
              </Card>
            </>
          ) : (
            <>
              <MetricGrid
                items={[
                  { label: "Documents", value: String(isdaSummary.document_count ?? 0), icon: <FileJson className="h-4 w-4" /> },
                  { label: "Field rows", value: String(isdaSummary.field_count ?? 0), icon: <TableProperties className="h-4 w-4" /> },
                  {
                    label: "Canonical fields",
                    value: String(bootstrap?.isda_config_summary.canonical_field_count ?? 0),
                    icon: <Sparkles className="h-4 w-4" />,
                  },
                ]}
              />

              <div className="grid gap-6 2xl:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
                <Card className="p-5 md:p-6">
                  <SectionHeader
                    eyebrow="ISDA upload"
                    title="Run DOCX extraction"
                    description="Hybrid rule and LLM extraction persists one document per country key and preserves the raw DOCX payload."
                  />
                  <div className="mt-5 grid gap-4 md:grid-cols-2">
                    <Field label="DOCX file">
                      <Input
                        type="file"
                        accept=".docx"
                        onChange={(event) => setIsdaUploadFile(event.target.files?.[0] ?? null)}
                      />
                    </Field>
                    <Field label="Country key override">
                      <Input value={isdaCountryOverride} onChange={(event) => setIsdaCountryOverride(event.target.value)} />
                    </Field>
                  </div>
                  <div className="mt-5 flex flex-wrap gap-3">
                    <Button onClick={() => void handleIsdaExtract()} disabled={isdaExtracting}>
                      <Upload className="mr-2 h-4 w-4" />
                      {isdaExtracting ? "Extracting..." : "Run ISDA extraction"}
                    </Button>
                    {isdaLatest ? (
                      <Button
                        variant="ghost"
                        onClick={() => handleDownloadJson(`isda_${isdaLatest.country_key}.json`, isdaLatest.structured)}
                      >
                        Download JSON
                      </Button>
                    ) : null}
                  </div>
                </Card>

                <Card className="p-5 md:p-6">
                  <SectionHeader
                    eyebrow="Latest document"
                    title="In-memory ISDA result"
                    description="The upload response is shown here immediately before you even switch to database views."
                  />
                  {isdaLatest ? (
                    <div className="space-y-4">
                      <MiniStat label="Country key" value={isdaLatest.country_key} icon={<ShieldCheck className="h-4 w-4" />} />
                      <DataTable rows={isdaLatest.structured.normalized_fields ?? []} />
                    </div>
                  ) : (
                    <EmptyState title="No ISDA result yet" copy="Upload a DOCX file to populate the latest ISDA panel." />
                  )}
                </Card>
              </div>

              <div className="grid gap-6 2xl:grid-cols-[minmax(0,0.78fr)_minmax(0,1.22fr)]">
                <Card className="p-5 md:p-6">
                  <SectionHeader
                    eyebrow="Documents"
                    title="Database inventory"
                    description="Select a document to inspect its structured JSON, field rows, and raw context."
                  />
                  <div className="mt-5 space-y-3">
                    {isdaDocuments.length === 0 ? (
                      <EmptyState title="No documents" copy="Run an ISDA extraction to create the first document record." />
                    ) : (
                      isdaDocuments.map((document) => (
                        <button
                          key={document.doc_id}
                          className={cn(
                            "w-full rounded-3xl border p-4 text-left transition",
                            selectedIsdaDocId === document.doc_id
                              ? "border-[hsl(var(--accent)/0.45)] bg-[hsl(var(--accent)/0.08)]"
                              : "border-line bg-white hover:bg-[hsl(var(--ink)/0.03)]",
                          )}
                          onClick={() => setSelectedIsdaDocId(document.doc_id)}
                        >
                          <div className="flex items-center justify-between gap-3">
                            <p className="font-semibold text-ink">{document.country_key}</p>
                            <Badge>{document.country || "Unknown"}</Badge>
                          </div>
                          <p className="mt-2 text-sm text-muted">{document.source_file}</p>
                          <p className="mt-1 text-xs uppercase tracking-[0.16em] text-muted">{document.uploaded_at}</p>
                        </button>
                      ))
                    )}
                  </div>
                </Card>

                <Card className="p-5 md:p-6">
                  <SectionHeader
                    eyebrow="Selected document"
                    title={isdaContext?.country_key ?? "Awaiting selection"}
                    description={isdaContext?.summary || "Choose a document to inspect normalized fields and raw payload context."}
                  />
                  <div className="mt-5 space-y-4">
                    <Field label="Search fields">
                      <Input value={isdaFieldSearch} onChange={(event) => setIsdaFieldSearch(event.target.value)} />
                    </Field>
                    <DataTable rows={isdaFieldRows} />
                    {isdaContext ? (
                      <div className="flex flex-wrap gap-3">
                        <Button variant="ghost" onClick={() => handleDownloadJson(`isda_${isdaContext.country_key}_structured.json`, isdaContext.extraction_json)}>
                          Download structured JSON
                        </Button>
                        <Button variant="ghost" onClick={() => handleDownloadJson(`isda_${isdaContext.country_key}_raw.json`, isdaContext.raw_docx_payload)}>
                          Download raw payload
                        </Button>
                      </div>
                    ) : null}
                  </div>
                </Card>
              </div>

              <div className="grid gap-6 2xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
                <Card className="p-5 md:p-6">
                  <SectionHeader
                    eyebrow="Read-only SQL"
                    title="Run custom ISDA queries"
                    description="This is intended for document-level investigation and field audits."
                  />
                  <div className="mt-5 space-y-4">
                    <Textarea value={isdaSql} onChange={(event) => setIsdaSql(event.target.value)} />
                    <Button onClick={() => void handleIsdaSql()}>Run ISDA SQL</Button>
                    <DataTable rows={isdaSqlRows} />
                  </div>
                </Card>

                <Card className="p-5 md:p-6">
                  <SectionHeader
                    eyebrow="Document chat"
                    title="Ask about the selected ISDA review"
                    description="Chat uses both the structured extraction JSON and the raw DOCX extraction payload."
                  />
                  <ChatPanel
                    history={isdaChatHistory}
                    value={isdaChatQuestion}
                    onChange={setIsdaChatQuestion}
                    onSubmit={() => void handleIsdaChat()}
                    loading={isdaChatLoading}
                    placeholder="Ask about jurisdiction, transaction coverage, or reviewer notes."
                    onClear={() => setIsdaChatHistory([])}
                  />
                </Card>
              </div>
            </>
          )}
        </main>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-2 block text-xs font-semibold uppercase tracking-[0.16em] text-muted">{label}</span>
      {children}
    </label>
  );
}

function SectionHeader({
  eyebrow,
  title,
  description,
}: {
  eyebrow: string;
  title: string;
  description: string;
}) {
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-muted">{eyebrow}</p>
      <h2 className="mt-1 font-display text-3xl leading-tight text-ink">{title}</h2>
      <p className="mt-2 max-w-3xl text-sm leading-6 text-muted">{description}</p>
    </div>
  );
}

function MiniStat({ label, value, icon }: { label: string; value: string; icon: ReactNode }) {
  return (
    <div className="rounded-3xl border border-white/70 bg-white/70 p-4 shadow-sm">
      <div className="flex items-center justify-between text-muted">
        <span className="text-xs font-semibold uppercase tracking-[0.18em]">{label}</span>
        {icon}
      </div>
      <p className="mt-3 text-xl font-semibold text-ink">{value}</p>
    </div>
  );
}

function MetricGrid({
  items,
}: {
  items: { label: string; value: string; icon: ReactNode }[];
}) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
      {items.map((item) => (
        <Card key={item.label} className="p-5">
          <div className="flex items-center justify-between text-muted">
            <span className="text-xs font-semibold uppercase tracking-[0.18em]">{item.label}</span>
            {item.icon}
          </div>
          <p className="mt-3 text-3xl font-semibold text-ink">{item.value}</p>
        </Card>
      ))}
    </div>
  );
}

function WorkflowButton({
  active,
  icon,
  title,
  description,
  onClick,
}: {
  active: boolean;
  icon: ReactNode;
  title: string;
  description: string;
  onClick: () => void;
}) {
  return (
    <button
      className={cn(
        "w-full rounded-3xl border px-4 py-4 text-left transition",
        active ? "border-[hsl(var(--accent)/0.45)] bg-[hsl(var(--accent)/0.08)]" : "border-line bg-white hover:bg-[hsl(var(--ink)/0.03)]",
      )}
      onClick={onClick}
    >
      <div className="flex items-center gap-3">
        <span className="inline-flex h-10 w-10 items-center justify-center rounded-2xl bg-[hsl(var(--ink)/0.06)] text-ink">
          {icon}
        </span>
        <div>
          <p className="font-semibold text-ink">{title}</p>
          <p className="mt-1 text-sm text-muted">{description}</p>
        </div>
      </div>
    </button>
  );
}

function TabbedTables({
  tabs,
}: {
  tabs: { id: string; label: string; content: ReactNode }[];
}) {
  const [active, setActive] = useState(tabs[0]?.id ?? "");
  const current = tabs.find((tab) => tab.id === active) ?? tabs[0];

  return (
    <div>
      <div className="flex flex-wrap gap-2">
        {tabs.map((tab) => (
          <Button key={tab.id} variant={tab.id === active ? "secondary" : "ghost"} onClick={() => setActive(tab.id)}>
            {tab.label}
          </Button>
        ))}
      </div>
      <div className="mt-4">{current?.content}</div>
    </div>
  );
}

function DataTable({ rows }: { rows: RowData[] }) {
  if (!rows.length) {
    return <EmptyState title="No rows" copy="There is no data for the current selection." />;
  }

  const columns = Array.from(
    rows.reduce((set, row) => {
      Object.keys(row).forEach((key) => set.add(key));
      return set;
    }, new Set<string>()),
  );

  return (
    <div className="overflow-hidden rounded-3xl border border-line">
      <div className="max-h-[30rem] overflow-auto bg-white">
        <table className="min-w-full border-separate border-spacing-0 text-sm">
          <thead className="sticky top-0 bg-[hsl(var(--ink)/0.06)] backdrop-blur">
            <tr>
              {columns.map((column) => (
                <th key={column} className="border-b border-line px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.16em] text-muted">
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, rowIndex) => (
              <tr key={rowIndex} className="odd:bg-white even:bg-[hsl(var(--ink)/0.02)]">
                {columns.map((column) => (
                  <td key={column} className="max-w-[320px] border-b border-line/60 px-4 py-3 align-top text-ink">
                    <span className="whitespace-pre-wrap break-words">{stringifyCell(row[column])}</span>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function RawPagesPanel({ pages }: { pages: RawPage[] }) {
  if (!pages.length) {
    return <EmptyState title="No raw pages" copy="Run an extraction to inspect extracted page text and tables." />;
  }

  return (
    <div className="space-y-3">
      {pages.map((page) => (
        <details key={page.page_number} className="overflow-hidden rounded-3xl border border-line bg-white">
          <summary className="cursor-pointer list-none px-5 py-4 font-semibold text-ink">Page {page.page_number}</summary>
          <div className="space-y-4 border-t border-line px-5 py-4">
            <div className="rounded-3xl bg-[hsl(var(--ink)/0.04)] p-4 text-sm leading-6 text-muted">
              {page.text ? page.text.slice(0, 2500) : "No extracted text"}
            </div>
            {page.tables.map((table) => (
              <div key={table.table_index}>
                <p className="mb-2 text-xs font-semibold uppercase tracking-[0.16em] text-muted">
                  Table {table.table_index}
                </p>
                <DataTable rows={table.rows.map((row) => Object.fromEntries(table.header.map((header, index) => [header || `column_${index + 1}`, row[index] ?? ""])))} />
              </div>
            ))}
          </div>
        </details>
      ))}
    </div>
  );
}

function ChatPanel({
  history,
  value,
  onChange,
  onSubmit,
  onClear,
  loading,
  placeholder,
}: {
  history: ChatMessage[];
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onClear: () => void;
  loading: boolean;
  placeholder: string;
}) {
  return (
    <div className="mt-5 grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
      <div className="rounded-3xl border border-line bg-white">
        <div className="flex items-center justify-between border-b border-line px-5 py-4">
          <div className="flex items-center gap-2">
            <MessageSquare className="h-4 w-4 text-[hsl(var(--accent-2))]" />
            <p className="font-semibold text-ink">Conversation</p>
          </div>
          <Button variant="ghost" onClick={onClear}>
            Clear
          </Button>
        </div>
        <div className="max-h-[28rem] space-y-3 overflow-auto p-5">
          {history.length === 0 ? (
            <EmptyState title="No messages yet" copy="Ask a question to start the document-aware chat flow." />
          ) : (
            history.map((message, index) => (
              <div
                key={`${message.role}-${index}`}
                className={cn(
                  "max-w-[92%] rounded-3xl px-4 py-3 text-sm leading-6",
                  message.role === "user"
                    ? "ml-auto bg-[hsl(var(--accent)/0.12)] text-ink"
                    : "bg-[hsl(var(--ink)/0.05)] text-ink",
                )}
              >
                <p className="mb-1 text-xs font-semibold uppercase tracking-[0.16em] text-muted">{message.role}</p>
                <p className="whitespace-pre-wrap">{message.content}</p>
              </div>
            ))
          )}
        </div>
      </div>
      <div className="rounded-3xl border border-line bg-[hsl(var(--ink)/0.03)] p-5">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-muted">Prompt</p>
        <p className="mt-2 text-sm leading-6 text-muted">
          Keep questions precise. The backend answers only from the extracted context it already has.
        </p>
        <div className="mt-4 space-y-4">
          <Textarea value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} />
          <Button onClick={onSubmit} disabled={loading}>
            <Bot className="mr-2 h-4 w-4" />
            {loading ? "Thinking..." : "Send question"}
          </Button>
        </div>
      </div>
    </div>
  );
}

function EmptyState({ title, copy }: { title: string; copy: string }) {
  return (
    <div className="rounded-3xl border border-dashed border-line bg-[hsl(var(--ink)/0.03)] p-6 text-center">
      <p className="font-semibold text-ink">{title}</p>
      <p className="mt-2 text-sm leading-6 text-muted">{copy}</p>
    </div>
  );
}

function filterRows(rows: RowData[], needle: string) {
  if (!needle.trim()) {
    return rows;
  }

  const normalizedNeedle = needle.toLowerCase();
  return rows.filter((row) => JSON.stringify(row).toLowerCase().includes(normalizedNeedle));
}

function stringifyCell(value: unknown) {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

function errorMessage(error: unknown) {
  if (error instanceof Error) {
    return error.message;
  }
  return "Request failed";
}
