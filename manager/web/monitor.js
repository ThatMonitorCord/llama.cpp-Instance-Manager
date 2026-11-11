/* Manager presentation uses the original LLama-GUI inference calculation core. */
(() => {
    "use strict";
    const root = window.LlamaGui = window.LlamaGui || {};
    const engines = new Map();
    const number = value => Number.isFinite(Number(value)) ? Number(value) : 0;
    function empty() {
        return {session:{prompt:0,generated:0,total:0}, context:{used:0,total:0,remaining:0},
            speed:{prompt:0,generated:0},requests:{processingBest:0,queued:0},slots:{busy:0,total:0}};
    }
    function sum(snapshots) {
        const total = empty();
        for (const snapshot of snapshots) {
            for (const [group, fields] of Object.entries(total)) {
                for (const field of Object.keys(fields)) total[group][field] += number(snapshot?.[group]?.[field]);
            }
        }
        total.context.percent = total.context.total ? total.context.used / total.context.total * 100 : 0;
        return total;
    }
    function sample(server, instance) {
        const key = `${server.id}/${instance.id}`;
        let entry = engines.get(key);
        if (!entry) {
            entry = {engine:root.inferenceStats.createInferenceStats(), lastSample:null};
            engines.set(key, entry);
        }
        if (!server.online || !instance.online || !instance.running) return empty();
        const runtime = instance.status?.active_runtime || {};
        const target = `${key}/${instance.pid || ""}/${runtime.generation || 0}/${runtime.port || ""}`;
        entry.engine.setTarget(target, {zeroBaseline:true});
        if (entry.lastSample !== instance.sampled_at) {
            const metrics = typeof instance.metrics === "string" ? root.inferenceStats.parseMetricsText(instance.metrics) : null;
            const slots = root.inferenceStats.normalizeSlots(instance.slots);
            entry.engine.applyPollResult({metricsOk:!!metrics, metricsValues:metrics, slotsOk:!!slots,
                slotsNormalized:slots, now:instance.sampled_at * 1000});
            entry.lastSample = instance.sampled_at;
        }
        return entry.engine.getSnapshot() || empty();
    }
    function reset(keys) {
        for (const key of keys) engines.get(key)?.engine.resetBaseline();
    }
    function collect(servers) {
        const seen = new Set();
        return servers.map(server => {
            const instances = [];
            for (const instance of server.instances || []) {
                const key = `${server.id}/${instance.id}`;
                if (seen.has(key)) continue;
                seen.add(key);
                instances.push({key, instance, snapshot:sample(server, instance)});
            }
            return {server, instances, snapshot:sum(instances.map(row => row.snapshot))};
        });
    }
    root.managerMonitor = {sum, empty, collect, reset};
})();
