// Execute the installed instance's own flag definitions/compiler, without changing it.
"use strict";
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const input = JSON.parse(fs.readFileSync(0, "utf8"));
const root = path.resolve(input.root);
const context = vm.createContext({window: {LlamaGui: {}}, console: {warn: () => {}, debug: () => {}}});
const html = fs.readFileSync(path.join(root, "ui/index.html"), "utf8");
const scripts = [...html.matchAll(/<script\b[^>]*\bsrc=["']([^"']+)["'][^>]*>/g)]
    .map(match => match[1].split("?")[0].replace(/^\//, "")).filter(src => src.startsWith("js/flags/"));
if (!scripts.length) throw new Error("This instance's flag definitions could not be located.");
for (const src of [...scripts, "js/flag-core.js"]) {
    const file = path.resolve(root, "ui", src);
    if (!file.startsWith(path.join(root, "ui") + path.sep)) throw new Error("Invalid script path");
    vm.runInContext(fs.readFileSync(file, "utf8"), context, {filename: src, timeout: 5000});
}
context.input = input;
const result = vm.runInContext(`(() => {
    const core = window.LlamaGui.flagCore;
    core.configure({getDefaultFlagValues: getDefaultValues, getFlags: () => FLAGS,
        normalizeMultiEnumValue: value => Array.isArray(value) ? value : [], shouldOmitSpeculativeFlag});
    core.setModelDirInfo(input.status);
    if (core.setBinaryTag) core.setBinaryTag(input.status.version || "");
    const data = input.preset;
    const state = {tool: data.tool || "llama-server", model: data.model || "",
        flags: core.buildEffectiveFlagValues({port: 8080, ...(data.flags || data)})};
    const result = core.buildLaunchArgs(state);
    if (result.error) throw new Error(result.error);
    return {tool: state.tool, args: result.args.flat(), env: result.env || {},
        launch_settings: core.captureLaunchSettings(state)};
})()`, context, {timeout: 5000});
process.stdout.write(JSON.stringify(result));
