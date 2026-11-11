(() => {
    "use strict";
    const $ = id => document.getElementById(id);
    const monitor = window.LlamaGui.managerMonitor;
    let config, fleet = {servers:[],jobs:[]}, tab = "instances", wizardStep = 0, adding = false;
    let startupInstance = null, setupRows = [], lastCount = 0, scanRows = [], pollTimer, logTicks = 0;
    const pending = new Map(), dismissedJobs = new Set();
    const instanceCards = new Map(), monitorCards = new Map();
    let hiddenCards = readStored("manager-hidden-cards", []), cardOrder = readStored("manager-card-order", []);
    let dragged = null, noticeTimer;

    function readStored(key, fallback) {
        try { return JSON.parse(localStorage.getItem(key)) ?? fallback; }
        catch (error) { console.debug("Could not read preference", error); return fallback; }
    }
    function saveStored(key, value) {
        try { localStorage.setItem(key, JSON.stringify(value)); }
        catch (error) { console.debug("Could not save preference", error); }
    }
    async function api(path, body) {
        const response = await fetch(path, {method:body === undefined ? "GET" : "POST",
            headers:{"Content-Type":"application/json"}, body:body === undefined ? undefined : JSON.stringify(body),
            signal:AbortSignal.timeout(20000)});
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
        return data;
    }
    function node(tag, className = "", text = "") {
        const el = document.createElement(tag); el.className = className; el.textContent = text; return el;
    }
    function button(text, action, className = "") {
        const el = node("button", className, text); el.type = "button";
        el.addEventListener("click", () => run(action)); return el;
    }
    function notice(message, error = false) {
        clearTimeout(noticeTimer); $("notice").textContent = message; $("notice").hidden = false;
        $("notice").classList.toggle("error", error); noticeTimer = setTimeout(() => { $("notice").hidden = true; }, error ? 14000 : 6000);
    }
    async function run(action) {
        try { await action(); } catch (error) { console.warn(error); notice(error.message, true); }
    }
    function on(id, event, action) { $(id).addEventListener(event, eventObject => run(() => action(eventObject))); }
    async function confirm(title, message) {
        $("confirm-title").textContent = title; $("confirm-message").textContent = message;
        const dialog = $("confirm-dialog"); dialog.returnValue = "cancel"; dialog.showModal();
        return new Promise(resolve => dialog.addEventListener("close", () => resolve(dialog.returnValue === "confirm"), {once:true}));
    }
    function address(server, port) {
        const hostname = server.local ? location.hostname : new URL(server.url).hostname;
        return `http://${hostname.includes(":") && !hostname.startsWith("[") ? `[${hostname}]` : hostname}:${port}`;
    }
    function instanceUrl(server, instance) {
        return address(server, instance.gui_port) + "/?preset=" + encodeURIComponent(instance.preset || "Manager defaults");
    }
    function setLink(el, url) { el.href = url; el.target = "_blank"; el.rel = "noopener"; }
    function setNav(open) {
        $("sidebar").classList.toggle("open", open); $("backdrop").hidden = !open;
        $("open-nav").setAttribute("aria-expanded", String(open));
        if (matchMedia("(max-width:680px)").matches) {
            $("main").inert = open; $("sidebar").inert = !open;
            (open ? $("close-nav") : $("open-nav")).focus();
        }
    }
    function switchTab(value) {
        tab = value;
        for (const panel of document.querySelectorAll(".section-panel")) panel.hidden = panel.id !== `section-${value}`;
        for (const item of document.querySelectorAll("[data-tab]")) {
            const active = item.dataset.tab === value; item.classList.toggle("active", active);
            if (active) item.setAttribute("aria-current", "page"); else item.removeAttribute("aria-current");
        }
        $("page-title").textContent = {instances:"Instances",monitor:"Monitor",servers:"LAN servers",settings:"Settings"}[value];
        $("page-eyebrow").textContent = {instances:"YOUR LOCAL INFERENCE",monitor:"LIVE ACTIVITY",servers:"YOUR CONNECTED MACHINES",settings:"INSTANCE MANAGER"}[value];
        if (matchMedia("(max-width:680px)").matches) setNav(false);
        saveStored("manager-tab", value);
        if (value === "servers") run(discover);
        render();
    }
    function options(select, entries, includeAll = false) {
        const old = select.value;
        const signature = JSON.stringify(entries);
        if (select.dataset.options === signature) return;
        select.dataset.options = signature; select.replaceChildren();
        if (includeAll) select.add(new Option("All servers", "all"));
        for (const entry of entries) select.add(new Option(entry.name, entry.id));
        if ([...select.options].some(option => option.value === old)) select.value = old;
    }
    async function refreshConfig() {
        config = await api("/api/config");
        $("sidebar-server").textContent = config.name;
        $("settings-name").value = config.name; $("settings-port").value = config.port; $("settings-login").checked = config.login_start;
        $("data-path").textContent = config.instances_dir;
        setLink($("local-address"), `${location.origin}/`);
    }
    async function poll() {
        clearTimeout(pollTimer);
        if (document.hidden) { pollTimer = setTimeout(poll, 2000); return; }
        try {
            fleet = await api("/api/fleet");
            $("connection").textContent = "● Live"; $("connection").className = "badge live";
            for (const [key, jobId] of pending) {
                const job = fleet.jobs.find(row => row.id === jobId);
                if (job && job.state !== "running") pending.delete(key);
            }
            render();
            if (tab === "monitor" && $("log-instance").value && $("follow-logs").checked && ++logTicks % 2 === 0) await refreshLogs();
        } catch (error) {
            $("connection").textContent = "Reconnecting…"; $("connection").className = "badge";
            console.debug("Manager poll failed", error);
        } finally { pollTimer = setTimeout(poll, 2000); }
    }
    function render() {
        const servers = fleet.servers;
        const all = servers.flatMap(server => (server.instances || []).map(instance => ({server,instance})));
        $("instance-count").textContent = all.length; $("server-count").textContent = servers.length;
        $("total-instances").textContent = all.length; $("running-instances").textContent = all.filter(row => row.instance.running).length;
        $("total-servers").textContent = servers.filter(server => server.online).length;
        $("sidebar-summary").textContent = `${all.filter(row => row.server.local && row.instance.running).length} models running locally`;
        if (servers[0]?.version) $("version").textContent = `Instance Manager ${servers[0].version}`;
        options($("instance-filter"), servers, true); options($("monitor-filter"), servers, true);
        options($("log-instance"), all.map(({server,instance}) => ({id:`${server.id}/${instance.id}`,name:`${server.name} / ${instance.name}`})));
        if (tab === "instances") renderInstances(all);
        if (tab === "monitor") renderMonitor();
        if (tab === "servers") renderServers();
        renderJobs();
    }
    function renderJobs() {
        const jobs = fleet.jobs.filter(job => !dismissedJobs.has(job.id));
        $("activity").hidden = !jobs.length; $("activity-count").textContent = jobs.some(job => job.state === "running") ? "· Working…" : "";
        const existing = new Map([...$("jobs").children].map(el => [el.dataset.id,el]));
        for (const job of jobs) {
            let el = existing.get(job.id);
            if (!el) {
                el = node("div", "job-row"); el.dataset.id = job.id;
                const content = node("div"); content.append(node("strong"),node("div","job-message"));
                el.append(content,node("span","badge"),button("×",() => {dismissedJobs.add(job.id);renderJobs();},"icon")); $("jobs").append(el);
            }
            el.querySelector("strong").textContent = job.title; el.querySelector(".job-message").textContent = job.message;
            el.querySelector(".badge").textContent = job.state; el.querySelector(".badge").className = `badge ${job.state === "error" ? "error" : job.state === "complete" ? "live" : ""}`;
            el.querySelector("button").hidden = job.state === "running"; existing.delete(job.id);
        }
        for (const el of existing.values()) el.remove();
    }
    function modelName(instance) {
        const model = instance.status?.active_runtime?.model;
        return typeof model === "string" ? model : model?.label || model?.value || model?.path || "—";
    }
    function makeInstanceCard(key) {
        const card = node("article","card instance-card"); card.dataset.key = key;
        card.innerHTML = '<div class="card-header"><div><div class="eyebrow"></div><h2></h2></div><span class="badge"></span></div><dl class="instance-meta"><dt>Model</dt><dd data-field="model"></dd><dt>Preset</dt><dd data-field="preset"></dd><dt>Panel</dt><dd><a data-field="panel"></a></dd><dt>Inference</dt><dd data-field="api" class="mono"></dd></dl><div class="actions" data-actions></div><p class="error" hidden></p><details><summary>Startup & installation</summary><div class="actions" data-settings></div><p class="instance-path mono"></p></details>';
        const actions = card.querySelector("[data-actions]");
        for (const [action,text] of [["start","Start"],["stop","Stop"],["restart","Restart"]]) {
            const control = button(text, () => controlInstance(card.server,card.instance,action), action === "start" ? "primary" : "");
            control.dataset.action = action; actions.append(control);
        }
        const open = node("a","button","Open instance ↗"); open.dataset.action = "open"; actions.append(open);
        const settings = card.querySelector("[data-settings]");
        settings.append(button("Startup settings", () => openStartup(card.instance)), button("Open panel only", () => controlInstance(card.server,card.instance,"panel")),
            button("Retry installation", () => controlInstance(card.server,card.instance,"retry")), button("Remove from manager", async () => {
                if (await confirm("Remove instance?", `Remove ${card.instance.name} from the manager? Its files and models will stay on disk.`)) {
                    await api("/api/remove", {instance_id:card.instance.id}); await refreshConfig(); await poll();
                }
            }));
        return card;
    }
    function renderInstances(all) {
        const keys = new Set();
        const filter = $("instance-filter").value, search = $("instance-search").value.toLowerCase(); let visible = 0;
        for (const {server,instance} of all) {
            const key = `${server.id}/${instance.id}`; keys.add(key);
            let card = instanceCards.get(key);
            if (!card) {card = makeInstanceCard(key);instanceCards.set(key,card);$("instance-list").append(card);}
            card.server = server; card.instance = instance;
            card.hidden = (filter !== "all" && server.id !== filter) || !`${instance.name} ${modelName(instance)}`.toLowerCase().includes(search);
            if (!card.hidden) visible++;
            card.querySelector(".eyebrow").textContent = `${server.name}${server.local ? " · THIS MACHINE" : ""}`;
            card.querySelector("h2").textContent = instance.name;
            const badge = card.querySelector(".badge");
            badge.textContent = pending.has(key) ? "Working…" : !server.online ? "Offline" : instance.install_state !== "ready" ? instance.install_state : instance.running ? "Running" : instance.online ? "Panel ready" : "Stopped";
            badge.className = `badge ${instance.running ? "live" : ""}`;
            card.querySelector('[data-field="model"]').textContent = modelName(instance);
            card.querySelector('[data-field="preset"]').textContent = instance.loaded_preset || "—";
            const panel = card.querySelector('[data-field="panel"]'); setLink(panel,instanceUrl(server,instance)); panel.textContent = address(server,instance.gui_port);
            const runtime = instance.status?.active_runtime;
            card.querySelector('[data-field="api"]').textContent = address(server,runtime?.port || instance.api_port);
            setLink(card.querySelector('[data-action="open"]'),instanceUrl(server,instance));
            for (const btn of card.querySelectorAll("button[data-action]")) btn.disabled = pending.has(key) || !server.online || instance.install_state !== "ready" || (btn.dataset.action === "stop" && !instance.online);
            card.querySelector("details").hidden = !server.local;
            card.querySelector(".instance-path").textContent = instance.path;
            const settings = card.querySelectorAll("[data-settings] button");
            settings[0].disabled = instance.install_state !== "ready";
            settings[1].disabled = pending.has(key) || instance.install_state !== "ready";
            settings[2].hidden = instance.install_state !== "error";
            settings[2].disabled = pending.has(key);
            settings[3].disabled = instance.online || ["pending","installing"].includes(instance.install_state);
            const error = card.querySelector("p.error"); error.textContent = instance.error || instance.install_error || "";error.hidden = !error.textContent;
        }
        for (const [key,card] of instanceCards) if (!keys.has(key)) {card.remove();instanceCards.delete(key);}
        $("instance-empty").hidden = !!visible;
    }
    async function controlInstance(server,instance,action) {
        const key = `${server.id}/${instance.id}`;
        if (pending.has(key)) return;
        pending.set(key,"pending"); render();
        try { const result = await api("/api/action",{server_id:server.id,instance_id:instance.id,action});pending.set(key,result.job);await poll(); }
        catch (error) {pending.delete(key);render();throw error;}
    }
    async function openStartup(instance) {
        startupInstance = instance;
        const names = await api(`/api/presets?instance_id=${encodeURIComponent(instance.id)}`);
        $("startup-title").textContent = instance.name;
        $("startup-preset").replaceChildren(new Option("Choose a preset", ""));
        for (const name of names) $("startup-preset").add(new Option(name,name));
        $("startup-preset").value = instance.preset || ""; $("startup-auto").checked = instance.auto_start;
        $("startup-dialog").showModal();
    }
    function fmt(value, decimals = 0) {return Number(value || 0).toLocaleString(undefined,{maximumFractionDigits:decimals,minimumFractionDigits:decimals});}
    function metric(label,value) {const el=node("div");el.append(node("span","metric-label",label),node("span","metric-value",value));return el;}
    function makeMonitorCard(id,type) {
        const card = node("article",`card monitor-card ${type}`);card.dataset.card = id;
        const head = node("div","card-header"), title = node("div"), tools = node("div","card-tools");
        title.append(node("div","eyebrow"),node("h2"));
        const drag = button("⠿",() => {},"drag");drag.title="Drag to reorder. Use Alt + Up or Down to move.";drag.setAttribute("aria-label","Reorder monitor card");drag.draggable=true;
        drag.addEventListener("dragstart",event => {dragged=id;event.dataTransfer.setData("text/plain",id);card.classList.add("dragging");});
        drag.addEventListener("dragend",() => {dragged=null;card.classList.remove("dragging");});
        drag.addEventListener("keydown",event => {
            if (event.altKey && ["ArrowUp","ArrowDown"].includes(event.key)) {
                event.preventDefault();const sibling = event.key === "ArrowUp" ? card.previousElementSibling : card.nextElementSibling;
                if (sibling) {$("monitor-cards").insertBefore(event.key === "ArrowUp" ? card : sibling,event.key === "ArrowUp" ? sibling : card);saveOrder();drag.focus();}
            }
        });
        card.addEventListener("dragover",event => event.preventDefault());
        card.addEventListener("drop",event => {event.preventDefault();const moving=monitorCards.get(dragged);if(moving&&moving!==card){$("monitor-cards").insertBefore(moving,card);saveOrder();}});
        tools.append(drag,button("Hide",() => {hiddenCards.push(id);saveStored("manager-hidden-cards",hiddenCards);renderMonitor();$("restore-cards").focus();}),node("span","badge"));
        head.append(title,tools);card.append(head,node("div","card-body"));
        if(type === "inference") {
            const body=card.querySelector(".card-body");
            body.innerHTML='<div class="token-grid"><div><span class="metric-label">Prompt</span><span class="metric-value" data-value="prompt"></span></div><div><span class="metric-label">Generated</span><span class="metric-value" data-value="generated"></span></div><div><span class="metric-label">Session total</span><span class="metric-value" data-value="total"></span></div></div><div class="context-line"><span class="metric-label">Context · <span data-context-label>combined slots</span></span><span class="mono" data-value="context"></span></div><div class="meter"><div></div></div><div class="rate-grid"><div><span class="metric-label">Avg prompt speed</span><span class="metric-value" data-value="prompt-speed"></span></div><div><span class="metric-label">Live generation speed</span><span class="metric-value" data-value="gen-speed"></span></div><div><span class="metric-label">Requests</span><span class="metric-value" data-value="requests"></span></div><div><span class="metric-label">Slots</span><span class="metric-value" data-value="slots"></span></div></div>';
            body.append(button("Reset session counters",() => {monitor.reset(card.keys || []);renderMonitor();},"reset-counters"));
        }
        monitorCards.set(id,card);$("monitor-cards").append(card);return card;
    }
    function saveOrder(){cardOrder=[...$("monitor-cards").children].map(el=>el.dataset.card);saveStored("manager-card-order",cardOrder);}
    function inferenceCard(id,title,subtitle,snapshot,keys,individual=false) {
        const card=monitorCards.get(id)||makeMonitorCard(id,"inference");card.keys=keys;
        card.querySelector("h2").textContent=title;card.querySelector(".eyebrow").textContent=subtitle;
        const data=monitor.sum([snapshot]), active=data.requests.processingBest;
        const badge=card.querySelector(".badge");badge.textContent=active ? `${fmt(active)} active` : "Idle";badge.className=`badge ${active ? "live" : ""}`;
        const values={prompt:`${fmt(data.session.prompt)} tokens`,generated:`${fmt(data.session.generated)} tokens`,total:`${fmt(data.session.total)} tokens`,
            context:`${fmt(data.context.used)} / ${fmt(data.context.total)} · ${fmt(data.context.remaining)} remaining`,
            "prompt-speed":`${fmt(data.speed.prompt,1)} tok/s`,"gen-speed":`${fmt(data.speed.generated,1)} tok/s`,
            requests:`${fmt(active)} active · ${fmt(data.requests.queued)} queued`,slots:`${fmt(data.slots.busy)} / ${fmt(data.slots.total)} busy`};
        for(const [key,value] of Object.entries(values))card.querySelector(`[data-value="${key}"]`).textContent=value;
        card.querySelector("[data-context-label]").textContent=individual ? "most-filled slot" : "combined";
        card.querySelector(".meter>div").style.width=`${Math.min(100,Math.max(0,data.context.percent))}%`;
        return card;
    }
    function bytes(value){return value == null ? "—" : `${fmt(value / 1073741824,1)} GB`;}
    function percent(value){return value == null ? "—" : `${fmt(value,1)}%`;}
    function hardwareCard(server){
        const id=`hardware/${server.id}`,card=monitorCards.get(id)||makeMonitorCard(id,"hardware");
        card.querySelector("h2").textContent="System & GPUs";card.querySelector(".eyebrow").textContent=server.name;
        card.querySelector(".badge").textContent=server.system ? "Live" : "Unavailable";
        const signature=JSON.stringify(server.system);if(card.dataset.sample===signature)return card;card.dataset.sample=signature;
        const body=card.querySelector(".card-body");body.replaceChildren();
        if(!server.system){body.append(node("p","muted","Start an instance control panel to view hardware activity."));return card;}
        const system=server.system.system||{},grid=node("div","hardware-grid");
        grid.append(metric("CPU",percent(system.cpu?.percent)),metric("RAM",`${bytes(system.memory?.used_bytes)} / ${bytes(system.memory?.total_bytes)}`),metric("Disk I/O",`${fmt((system.disk?.read_bytes_per_second||0)/1048576,1)} ↓ ${fmt((system.disk?.write_bytes_per_second||0)/1048576,1)} ↑ MB/s`));body.append(grid);
        for(const gpu of server.system.gpus||[]){const el=node("div","gpu"),head=node("div","gpu-head"),stats=node("div","hardware-grid");head.append(node("strong","",gpu.name||gpu.id||"GPU"),node("span","muted",gpu.vendor||""));stats.append(metric("Utilization",percent(gpu.utilization_percent)),metric("VRAM",`${bytes(gpu.memory_used_bytes)} / ${bytes(gpu.memory_total_bytes)}`),metric("Temperature",gpu.temperature_c==null?"—":`${fmt(gpu.temperature_c)} °C`));el.append(head,stats);body.append(el);}
        return card;
    }
    function renderMonitor(){
        const filter=$("monitor-filter").value,servers=fleet.servers.filter(server=>filter==="all"||server.id===filter);
        const rows=monitor.collect(servers),keys=rows.flatMap(row=>row.instances.map(item=>item.key)),visible=new Set();
        const add=card=>visible.add(card.dataset.card);
        add(inferenceCard("combined","Combined inference",filter==="all"?"ALL CONNECTED SERVERS":servers[0]?.name||"SERVER",monitor.sum(rows.map(row=>row.snapshot)),keys));
        for(const row of rows){
            add(inferenceCard(`server/${row.server.id}`,"Inference",row.server.name,row.snapshot,row.instances.map(item=>item.key)));
            add(hardwareCard(row.server));
            if($("show-individual").checked)for(const item of row.instances)add(inferenceCard(item.key,item.instance.name,`${row.server.name} · INFERENCE`,item.snapshot,[item.key],true));
        }
        for(const [id,card] of monitorCards)card.hidden=!visible.has(id)||hiddenCards.includes(id);
        // Move existing nodes only when needed, preserving focus and button state.
        const ordered=[...monitorCards.keys()].sort((a,b)=>{const ai=cardOrder.indexOf(a),bi=cardOrder.indexOf(b);return (ai<0?9999:ai)-(bi<0?9999:bi);});
        let previous=null;for(const id of ordered){const card=monitorCards.get(id);if(previous?previous.nextElementSibling!==card:$("monitor-cards").firstElementChild!==card)$("monitor-cards").insertBefore(card,previous?previous.nextElementSibling:$("monitor-cards").firstElementChild);previous=card;}
        $("sample-time").textContent=`Updated ${new Date().toLocaleTimeString()}`;
    }
    async function refreshLogs(){
        const value=$("log-instance").value;if(!value)return;const [server_id,instance_id]=value.split("/");
        const data=await api(`/api/logs?server_id=${encodeURIComponent(server_id)}&instance_id=${encodeURIComponent(instance_id)}`);
        const lines=data.lines||data.output||[];$("log-output").textContent=lines.map(line=>typeof line==="string"?line:line.text||JSON.stringify(line)).join("\n")||"No output yet.";
        if($("follow-logs").checked)$("log-output").scrollTop=$("log-output").scrollHeight;
    }
    function renderServers(){
        const signature=JSON.stringify(fleet.servers.map(row=>[row.id,row.name,row.online,row.url]));if($("connected-servers").dataset.signature===signature)return;$("connected-servers").dataset.signature=signature;
        $("connected-servers").replaceChildren();
        for(const server of fleet.servers){const card=node("article","card"),head=node("div","card-header");head.append(node("h2","",server.name),node("span",`badge ${server.online?"live":""}`,server.online?"Connected":"Offline"));card.append(head,node("p","mono",server.local?location.origin:server.url));if(!server.local)card.append(button("Disconnect",async()=>{await api("/api/disconnect",{id:server.id});await refreshConfig();await poll();}));$("connected-servers").append(card);}
    }
    async function discover(){
        const result=await api("/api/discovery");scanRows=result.managers;
        $("discovered").replaceChildren();$("setup-discovery").replaceChildren();
        const connected=new Set((config?.peers||[]).map(row=>row.id));
        for(const peer of scanRows){
            const row=node("div","peer-row"),content=node("div");content.append(node("strong","",peer.name),node("small","mono",peer.url));
            const connect=button(connected.has(peer.id)?"Connected":"Connect",async()=>{await api("/api/connect",{url:peer.url});await refreshConfig();await discover();});connect.disabled=connected.has(peer.id);row.append(content,connect);$("discovered").append(row);
            const choice=node("label","check"),check=node("input");check.type="checkbox";check.value=peer.url;check.checked=connected.has(peer.id);check.disabled=connected.has(peer.id);choice.append(check,document.createTextNode(`${peer.name} · ${peer.url}`));$("setup-discovery").append(choice);
        }
        if(!scanRows.length){$("discovered").append(node("p","muted","No other managers found yet. Discovery refreshes while this page is open."));$("setup-discovery").append(node("p","muted","No other managers found yet. You can connect a server later."));}
        if(result.error)$("discovered").append(node("p","error",`Discovery unavailable: ${result.error}`));
    }
    function readRows(){return [...$("setup-rows").children].map(row=>({name:row.querySelector("[data-name]").value,gui_port:Number(row.querySelector("[data-gui]").value),api_port:Number(row.querySelector("[data-api]").value)}));}
    async function allocate(){
        const count=Number($("setup-count").value);setupRows=await api(`/api/ports?count=${count}`);lastCount=count;$("setup-rows").replaceChildren();
        for(const [index,row] of setupRows.entries()){
            const el=node("div","port-row");
            for(const [field,type,attr] of [["name","text","name"],["gui_port","number","gui"],["api_port","number","api"]]){const input=node("input");input.type=type;input.value=row[field];input.required=true;input.dataset[attr]="";input.setAttribute("aria-label",`${field==="name"?"Name":field==="gui_port"?"Control panel port":"Inference API port"} for instance ${index+1}`);if(type==="number"){input.min=1024;input.max=65535;}el.append(input);}$("setup-rows").append(el);
        }
    }
    function showStep(step){wizardStep=step;for(const page of document.querySelectorAll("[data-page]"))page.hidden=Number(page.dataset.page)!==step;for(const item of document.querySelectorAll("[data-step]"))item.classList.toggle("active",Number(item.dataset.step)===step);$("setup-back").hidden=step===0;$("setup-next").hidden=step===2;$("setup-install").hidden=step!==2;$("setup-error").hidden=true;}
    async function openSetup(isAdding){
        adding=isAdding;lastCount=0;setupRows=[];$("setup-rows").replaceChildren();$("setup-title").textContent=adding?"Add llama.cpp instances":"Set up your server";
        $("server-fields").hidden=adding;$("cancel-setup").hidden=!adding;
        $("setup-name").value=config.name;$("setup-port").value=config.port;$("setup-login").checked=config.login_start;
        $("setup-directory").value=config.instances_dir;$("setup-count").value=1;$("setup-share").checked=false;$("shared-folder-label").hidden=true;$("setup-models").required=false;
        showStep(0);$("setup-dialog").showModal();await discover();
    }
    function review(){
        $("setup-review").replaceChildren();
        const lines=[["Server",$("setup-name").value],["Manager port",$("setup-port").value],["Instances folder",$("setup-directory").value]];
        for(const row of readRows())lines.push([row.name,`Panel ${row.gui_port} · API ${row.api_port}`]);
        if($("setup-share").checked)lines.push(["Shared models",$("setup-models").value]);
        for(const [name,value]of lines){const row=node("div","review-row");row.append(node("span","",name),node("span","",value));$("setup-review").append(row);}
    }
    function reconnect(port){const url=new URL(location.href);url.port=port;notice("Manager is moving to its new port…");setTimeout(()=>location.assign(url),1800);}

    for(const item of document.querySelectorAll("[data-tab]"))item.addEventListener("click",()=>switchTab(item.dataset.tab));
    on("open-nav","click",()=>setNav(true));on("close-nav","click",()=>setNav(false));on("backdrop","click",()=>setNav(false));
    document.addEventListener("keydown",event=>{
        if(!$("sidebar").classList.contains("open"))return;
        if(event.key==="Escape")setNav(false);
        if(event.key==="Tab"){const controls=[...$("sidebar").querySelectorAll("button,a,select,summary")].filter(el=>el.offsetParent!==null);const first=controls[0],last=controls.at(-1);if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}}
    });
    const mobile=matchMedia("(max-width:680px)");function responsive(){if(mobile.matches){$("sidebar").inert=!$("sidebar").classList.contains("open");}else{$("sidebar").inert=false;$("main").inert=false;$("backdrop").hidden=true;$("sidebar").classList.remove("open");}}mobile.addEventListener("change",responsive);responsive();
    const theme=readStored("manager-theme","nebula");if([...$("theme").options].some(option=>option.value===theme))$("theme").value=theme;document.documentElement.dataset.theme=$("theme").value;
    on("theme","change",()=>{document.documentElement.dataset.theme=$("theme").value;saveStored("manager-theme",$("theme").value);});
    on("instance-filter","change",render);on("instance-search","input",render);on("monitor-filter","change",renderMonitor);on("show-individual","change",()=>{saveStored("manager-show-individual",$("show-individual").checked);renderMonitor();});$("show-individual").checked=readStored("manager-show-individual",true);
    on("restore-cards","click",()=>{hiddenCards=[];saveStored("manager-hidden-cards",[]);renderMonitor();});
    on("refresh-logs","click",refreshLogs);on("log-instance","change",refreshLogs);on("scan","click",discover);on("setup-scan","click",discover);
    on("connect-form","submit",async event=>{event.preventDefault();await api("/api/connect",{url:$("peer-url").value});$("peer-url").value="";await refreshConfig();await poll();await discover();});
    on("add-instances","click",()=>openSetup(true));on("cancel-setup","click",()=>$("setup-dialog").close());
    $("setup-dialog").addEventListener("cancel",event=>{if(!adding)event.preventDefault();});
    on("setup-share","change",()=>{$("shared-folder-label").hidden=!$("setup-share").checked;$("setup-models").required=$("setup-share").checked;});
    on("rescan-ports","click",allocate);on("setup-back","click",()=>showStep(wizardStep-1));
    on("setup-next","click",async()=>{
        for(const input of document.querySelector(`[data-page="${wizardStep}"]`).querySelectorAll("input"))if(!input.checkValidity()){input.reportValidity();return;}
        if(wizardStep===0){if(lastCount!==Number($("setup-count").value))await allocate();showStep(1);}else{review();showStep(2);await discover();}
    });
    on("setup-form","submit",async event=>{
        event.preventDefault();if(wizardStep!==2)return;$("setup-install").disabled=true;
        try {
            const body={name:$("setup-name").value,port:Number($("setup-port").value),login_start:$("setup-login").checked,directory:$("setup-directory").value,
                models_dir:$("setup-share").checked?$("setup-models").value:"",instances:readRows(),firewall:$("setup-firewall").checked};
            const urls=[...$("setup-discovery").querySelectorAll("input:checked:not(:disabled)")].map(input=>input.value);
            for(const url of urls)await api("/api/connect",{url});
            const result=await api(adding?"/api/install":"/api/setup",body);
            $("setup-dialog").close();
            if(result.port&&result.port!==Number(location.port)){reconnect(result.port);return;}
            await refreshConfig();switchTab("instances");await poll();
        }catch(error){$("setup-error").textContent=error.message;$("setup-error").hidden=false;}
        finally{$("setup-install").disabled=false;}
    });
    for(const control of document.querySelectorAll("[data-close]"))control.addEventListener("click",()=>$(control.dataset.close).close());
    on("startup-form","submit",async event=>{event.preventDefault();await api("/api/startup",{instance_id:startupInstance.id,preset:$("startup-preset").value,auto_start:$("startup-auto").checked});$("startup-dialog").close();await refreshConfig();notice("Startup settings saved.");await poll();});
    on("settings-form","submit",async event=>{event.preventDefault();const result=await api("/api/settings",{name:$("settings-name").value,port:Number($("settings-port").value),login_start:$("settings-login").checked});if(result.port!==Number(location.port))reconnect(result.port);else{await refreshConfig();notice("Settings saved.");}});
    on("allow-lan","click",async()=>{await api("/api/firewall",{});await poll();});
    on("check-update","click",async()=>{$("check-update").disabled=true;try{const update=await api("/api/update");$("update-status").textContent=update.current===update.latest?`You're up to date (${update.current}).`:`Version ${update.latest} is available. Current version: ${update.current}.`;$("download-update").hidden=!update.download||update.current===update.latest;if(update.download)setLink($("download-update"),update.download);}finally{$("check-update").disabled=false;}});
    document.addEventListener("visibilitychange",()=>{if(!document.hidden)run(poll);});
    setInterval(()=>{if(!document.hidden&&(tab==="servers"||$("setup-dialog").open&&wizardStep===2))run(discover);},10000);
    run(async()=>{
        await refreshConfig();
        const saved=readStored("manager-tab","instances");switchTab(["instances","monitor","servers","settings"].includes(saved)?saved:"instances");
        await poll();if(!config.configured)await openSetup(false);
    });
})();
