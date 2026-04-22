import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";


const NODE_NAMES = new Set(["Magic Prompt Select", "MagicPromptSelect"]);
const PROMPT_WIDGET_NAME = "prompt_name";
const REFRESH_WIDGET_NAME = "Refresh Prompts";
const PROMPTS_ROUTE_PATH = "/magicwrapper/prompts";
const PROMPTS_PLACEHOLDER = "<no prompts configured>";


function chainCallback(object, property, callback) {
    if (object == null) {
        return;
    }

    const original = object[property];
    object[property] = function () {
        const result = typeof original === "function" ? original.apply(this, arguments) : undefined;
        callback.apply(this, arguments);
        return result;
    };
}


function getPromptWidget(node) {
    return node.widgets?.find((widget) => widget.name === PROMPT_WIDGET_NAME);
}


function ensureRefreshWidget(node) {
    const existing = node.widgets?.find((widget) => widget.name === REFRESH_WIDGET_NAME);
    if (existing) {
        return existing;
    }

    return node.addWidget("button", REFRESH_WIDGET_NAME, "refresh", () => {
        refreshPromptOptions(node);
    });
}


async function fetchPromptNames() {
    try {
        const response = await api.fetchApi(PROMPTS_ROUTE_PATH, { cache: "no-store" });
        const data = await response.json();

        if (!response.ok) {
            console.error("Magic Prompt Select failed to load prompts:", data?.error ?? response.statusText);
            return [PROMPTS_PLACEHOLDER];
        }

        const items = Array.isArray(data?.items) ? data.items : [];
        const names = items
            .map((item) => item?.name)
            .filter((name) => typeof name === "string" && name.length > 0);

        return names.length > 0 ? names : [PROMPTS_PLACEHOLDER];
    } catch (error) {
        console.error("Magic Prompt Select failed to refresh prompts:", error);
        return [PROMPTS_PLACEHOLDER];
    }
}


async function refreshPromptOptions(node) {
    const promptWidget = getPromptWidget(node);
    if (!promptWidget) {
        return;
    }

    const currentValue = promptWidget.value;
    const names = await fetchPromptNames();

    promptWidget.options = promptWidget.options || {};
    promptWidget.options.values = names;
    promptWidget.value = names.includes(currentValue) ? currentValue : names[0];

    node.setDirtyCanvas?.(true, true);
    node.graph?.setDirtyCanvas?.(true, true);
}


function addPromptSelectExtension(nodeType) {
    chainCallback(nodeType.prototype, "onNodeCreated", function () {
        ensureRefreshWidget(this);
        Promise.resolve().then(() => refreshPromptOptions(this));
    });

    chainCallback(nodeType.prototype, "onConfigure", function () {
        ensureRefreshWidget(this);
    });
}


app.registerExtension({
    name: "ComfyUI.MagicWrapper.PromptSelect",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!NODE_NAMES.has(nodeData.name)) {
            return;
        }

        addPromptSelectExtension(nodeType);
    },
});
