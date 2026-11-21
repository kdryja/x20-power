// X20 Power — hand-written Decky frontend (no build step).
// Uses the globals Decky Loader provides: window.SP_REACT, window.DFL and the loader API.
const manifest = { name: "X20 Power" };
const API_VERSION = 2;
const internalAPIConnection = window.__DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit;
if (!internalAPIConnection) {
    throw new Error("[X20 Power] Decky loader API not initialised");
}
let api;
try {
    api = internalAPIConnection.connect(API_VERSION, manifest.name);
} catch {
    api = internalAPIConnection.connect(1, manifest.name);
}
const callable = api.callable;
const definePlugin = (fn) => (...args) => fn(...args);

const React = window.SP_REACT;
const DFL = window.DFL;
const h = React.createElement;

const getState = callable("get_state");
const setChargeLimit = callable("set_charge_limit");
const setTravelMode = callable("set_travel_mode");
const setGame = callable("set_game");
const setTdp = callable("set_tdp");
const resume = callable("resume");

function currentGame() {
    const app = DFL.Router && DFL.Router.MainRunningApp;
    return {
        id: app && app.appid ? String(app.appid) : "default",
        name: (app && app.display_name) || "",
    };
}

function statusLine(st) {
    if (!st) return "…";
    const parts = [`${st.capacity ?? "?"}%`, st.status ?? "?"];
    if (st.current_ma) parts.push(`${(st.current_ma / 1000).toFixed(1)} A`);
    parts.push(st.charger_w ? `charger ${st.charger_w} W` : "no charger");
    return parts.join(" · ");
}

function tdpContext(t) {
    const who = t.game_id === "default" ? "Default" : (t.game_name || `App ${t.game_id}`);
    const where = t.source === "ac" ? "on charger" : "on battery";
    const own = t.game_id === "default" ? "" : (t.own ? "" : " (using default)");
    return `${who} · ${where}${own}`;
}

function limitsLine(t) {
    const l = t.limits || {};
    const apu = t.apu_w == null ? "" : ` · APU ${t.apu_w} W`;
    return `SPL ${l.ppt_pl1_spl} / SPPT ${l.ppt_pl2_sppt} / FPPT ${l.ppt_pl3_fppt} W · ${t.platform_profile}${apu}`;
}

function Content() {
    const [st, setSt] = React.useState(null);
    const [busy, setBusy] = React.useState(false);
    const [err, setErr] = React.useState(null);
    const [tdpDraft, setTdpDraft] = React.useState(null);
    const tdpTimer = React.useRef(null);

    const refresh = async () => {
        try {
            setSt(await getState());
            setErr(null);
        } catch (e) {
            setErr(String(e));
        }
    };

    React.useEffect(() => {
        refresh();
        const t = setInterval(refresh, 3000);
        return () => {
            clearInterval(t);
            if (tdpTimer.current) clearTimeout(tdpTimer.current);
        };
    }, []);

    const run = (fn) => async (value) => {
        setBusy(true);
        try {
            setSt(await fn(value));
            setErr(null);
        } catch (e) {
            setErr(String(e));
        } finally {
            setBusy(false);
        }
    };

    const onTdp = (value) => {
        setTdpDraft(value);
        if (tdpTimer.current) clearTimeout(tdpTimer.current);
        tdpTimer.current = setTimeout(async () => {
            try {
                setSt(await setTdp(value));
                setErr(null);
            } catch (e) {
                setErr(String(e));
            } finally {
                setTdpDraft(null);
            }
        }, 400);
    };

    let desc = "Holds the battery at 80%. The X20 firmware only supports 80% or full.";
    if (st && st.charge_limit === null) desc += " Not set from here yet.";
    if (st && !st.debugfs) desc = "asus-nb-wmi debugfs is missing, so the limit can't be set.";

    const t = st && st.tdp;
    const tdpSection = t && t.supported
        ? h(DFL.PanelSection, { title: "TDP" },
            h(DFL.PanelSectionRow, null,
                h(DFL.SliderField, {
                    label: "TDP",
                    description: tdpContext(t),
                    value: tdpDraft ?? t.value,
                    min: t.min,
                    max: t.max,
                    step: 1,
                    showValue: true,
                    valueSuffix: " W",
                    onChange: onTdp,
                })),
            h(DFL.PanelSectionRow, null,
                h(DFL.Field, { label: "Limits now", focusable: true }, limitsLine(t))))
        : null;

    return h(React.Fragment, null,
        tdpSection,
        h(DFL.PanelSection, { title: "Battery" },
            h(DFL.PanelSectionRow, null,
                h(DFL.ToggleField, {
                    label: "Limit charging to 80%",
                    description: desc,
                    checked: !!(st && st.charge_limit),
                    disabled: busy || !st || !st.debugfs,
                    onChange: run(setChargeLimit),
                })),
            h(DFL.PanelSectionRow, null,
                h(DFL.ToggleField, {
                    label: "Travel Mode",
                    description: st && st.travel_mode === null
                        ? "Couldn't read Travel Mode."
                        : "Caps charging at 65 W. Same setting as in Armoury Crate; it stays set across reboots.",
                    checked: !!(st && st.travel_mode),
                    disabled: busy || !st || st.travel_mode === null,
                    onChange: run(setTravelMode),
                })),
            h(DFL.PanelSectionRow, null,
                h(DFL.Field, { label: "Now", focusable: true }, statusLine(st))),
            err ? h(DFL.PanelSectionRow, null, h(DFL.Field, { label: "Error" }, err)) : null)
    );
}

function Icon() {
    return h("svg", { viewBox: "0 0 24 24", width: "1em", height: "1em", fill: "currentColor" },
        h("path", { d: "M15 3h-2V1h-2v2H9a2 2 0 0 0-2 2v15a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2zm0 17H9V9h6v11z" }));
}

var index = definePlugin(() => {
    // Follow the running game so its TDP profile applies (same 2 s polling as SimpleDeckyTDP).
    let lastGame = null;
    const syncGame = (force) => {
        const g = currentGame();
        if (!force && lastGame === g.id) return;
        lastGame = g.id;
        setGame(g.id, g.name).catch((e) => console.error("[X20 Power] set_game failed", e));
    };
    syncGame(true);
    const gameTimer = setInterval(() => syncGame(false), 2000);

    let resumeReg = null;
    try {
        resumeReg = window.SteamClient?.System?.RegisterForOnResumeFromSuspend?.(() => {
            resume().catch((e) => console.error("[X20 Power] resume failed", e));
        });
    } catch (e) {
        console.error("[X20 Power] resume hook failed", e);
    }

    return {
        name: "X20 Power",
        titleView: h("div", { className: DFL.staticClasses?.Title }, "X20 Power"),
        content: h(Content, null),
        icon: h(Icon, null),
        onDismount() {
            clearInterval(gameTimer);
            try { resumeReg?.unregister?.(); } catch (e) { console.error(e); }
        },
    };
});

export { index as default };
