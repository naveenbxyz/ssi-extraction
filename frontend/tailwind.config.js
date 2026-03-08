export default {
    content: ["./index.html", "./src/**/*.{ts,tsx}"],
    theme: {
        extend: {
            colors: {
                ink: "hsl(var(--ink))",
                surface: "hsl(var(--surface))",
                panel: "hsl(var(--panel))",
                line: "hsl(var(--line))",
                accent: "hsl(var(--accent))",
                accent2: "hsl(var(--accent-2))",
                muted: "hsl(var(--muted))",
                success: "hsl(var(--success))",
                danger: "hsl(var(--danger))"
            },
            borderRadius: {
                xl2: "1.5rem"
            },
            boxShadow: {
                panel: "0 20px 60px rgba(23, 36, 53, 0.12)",
                glow: "0 18px 45px rgba(196, 87, 39, 0.18)"
            },
            fontFamily: {
                display: ["Iowan Old Style", "Palatino Linotype", "Book Antiqua", "serif"],
                sans: ["Avenir Next", "Segoe UI", "Helvetica Neue", "sans-serif"]
            },
            backgroundImage: {
                grid: "linear-gradient(to right, rgba(43,63,86,0.08) 1px, transparent 1px), linear-gradient(to bottom, rgba(43,63,86,0.08) 1px, transparent 1px)"
            }
        }
    },
    plugins: [],
};
