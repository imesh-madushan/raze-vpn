local controller = noctalia.expandPath("~/.local/share/raze-vpn/app/controller.py")
local state = {}
local page = "main"
local busy = false
local busyAction = nil
local refreshing = false
local notice = ""
local noticeAt = 0
local errorMessage = false
local logs = "Loading logs…"
local fields = {}
local checkBusy = false
local newName = ""
local newSource = ""
local jsonContent = ""
local jsonRevision = ""
local jsonName = ""
local updateInfo = {}

-- last connection check, kept between polls
local lastCheck = nil
local lastCheckKey = nil
local autoCheckedFor = nil

noctalia.setUpdateInterval(2000)

-- ───────────────────────── helpers ─────────────────────────

local function setNotice(text, isError)
    notice = text or ""
    errorMessage = isError == true
    noticeAt = os.time()
end

local function fmtDuration(seconds)
    seconds = tonumber(seconds) or 0
    return string.format("%02d:%02d:%02d", math.floor(seconds / 3600), math.floor(seconds / 60) % 60, seconds % 60)
end

local function fmtAgo(timestamp)
    local age = math.floor(math.max(0, os.time() - (tonumber(timestamp) or 0)))
    if age < 5 then return "just now" end
    if age < 60 then return age .. "s ago" end
    return math.floor(age / 60) .. "m ago"
end

local function updateLive()
    local key = tostring(state.active) .. ":" .. tostring(state.invocation)
    if key ~= lastCheckKey then
        lastCheck = nil
        lastCheckKey = key
    end
    if not state.active then autoCheckedFor = nil end
end

-- ───────────────────────── building blocks ─────────────────────────

local function header(title, backAction)
    local lead
    if backAction then
        lead = ui.button({glyph = "arrow-left", variant = "ghost", tooltip = "Back", onClick = backAction})
    else
        lead = ui.glyph({name = "shield-lock", size = 24, color = "primary"})
    end
    return ui.row({align = "center", gap = 10}, {
        lead,
        ui.column({gap = 1, flexGrow = 1}, {
            ui.label({text = title, fontSize = 18, fontWeight = "bold"}),
            ui.label({text = state.machine or "raze", color = "on_surface_variant", fontSize = 11}),
        }),
        ui.button({glyph = "x", variant = "ghost", tooltip = "Close", onClick = "closePanel"}),
    })
end

local function banner()
    if notice == "" then return nil end
    local color = errorMessage and "error" or "primary"
    return ui.row({align = "center", gap = 10, padding = 12, radius = 12, fill = color .. "/0.12"}, {
        ui.glyph({name = errorMessage and "alert-circle" or "circle-check", size = 18, color = color}),
        ui.label({text = notice, color = color, fontSize = 12, maxWidth = 330, maxLines = 3, flexGrow = 1}),
    })
end

local function chip(glyph, text, color)
    return ui.row({align = "center", gap = 6, padding = 9, radius = 12, fill = "surface_variant/0.45", flexGrow = 1}, {
        ui.glyph({name = glyph, size = 15, color = color or "on_surface_variant"}),
        ui.label({text = text, fontSize = 12, color = color, maxWidth = 150, maxLines = 1}),
    })
end

local function card(children, extra)
    local props = {gap = 10, padding = 14, radius = 14, fill = "surface_variant/0.4"}
    for k, v in pairs(extra or {}) do props[k] = v end
    return ui.column(props, children)
end

local function logColor(line)
    local l = string.lower(line)
    if l:find("error", 1, true) or l:find("fatal", 1, true) or l:find("fail", 1, true) or l:find("denied", 1, true) then return "error" end
    if l:find("warn", 1, true) then return "tertiary" end
    if l:find("restored", 1, true) or l:find("started", 1, true) or l:find("connected", 1, true) then return "primary" end
    return "on_surface_variant"
end

-- ───────────────────────── main page ─────────────────────────

local function exitCard()
    local title, sub, valueColor = "Not checked yet", "Runs automatically after you connect", nil
    if checkBusy then
        title, sub = "Checking…", "Verifying HTTPS and exit IP"
    elseif lastCheck then
        local age = lastCheck.checked_at and fmtAgo(lastCheck.checked_at) or ""
        if lastCheck.ok then
            if lastCheck.ip and lastCheck.ip ~= "" then
                title = lastCheck.ip .. ((lastCheck.country or "") ~= "" and (" · " .. lastCheck.country) or "")
            else
                title = "HTTPS reachable"
            end
            sub = ((lastCheck.ip or "") == "" and "Exit IP unavailable · " or "") .. (lastCheck.latency_ms and (lastCheck.latency_ms .. " ms · ") or "") .. age
        else
            title, valueColor = "Check failed", "error"
            sub = (lastCheck.error and lastCheck.error ~= "") and lastCheck.error or "HTTPS did not respond"
        end
    elseif not state.active then
        title, sub = "VPN is off", "Check to see your current public IP"
    end
    local hasIp = lastCheck and lastCheck.ok and lastCheck.ip and lastCheck.ip ~= ""
    return ui.row({align = "center", gap = 10, padding = 10, radius = 12, fill = "surface_variant/0.4"}, {
        ui.glyph({name = "world", size = 20, color = valueColor or (state.active and "primary" or "on_surface_variant")}),
        ui.column({gap = 2, flexGrow = 1}, {
            ui.label({text = "Exit IP", fontSize = 11, color = "on_surface_variant"}),
            ui.label({text = title, fontSize = 15, fontWeight = "bold", color = valueColor, maxWidth = 235, maxLines = 1}),
            ui.label({text = sub, fontSize = 11, color = "on_surface_variant", maxWidth = 235, maxLines = 1}),
        }),
        ui.button({glyph = "copy", variant = "ghost", controlSize = "sm", tooltip = "Copy IP", enabled = hasIp == true, onClick = "copyIp"}),
        ui.button({glyph = "refresh", variant = "ghost", controlSize = "sm", tooltip = "Check now", enabled = not checkBusy and not busy, onClick = "checkNow"}),
    })
end

local function renderMain()
    local active = state.active == true
    local leak = active and state.ipv6_disabled == false
    local color = (leak and "error") or (active and "primary") or "on_surface_variant"
    local transition = busy and (busyAction == "start" or busyAction == "stop" or busyAction == "switch")

    local status = active and "Connected" or "Disconnected"
    local sub = active and ("Public traffic uses " .. ((state.active_profile or "") ~= "" and state.active_profile or "your VPN")) or "Using your normal connection"
    if state.state == "failed" and not active then
        status, color, sub = "Connection failed", "error", "Open Logs to see the cause"
    end
    if transition then
        color = "on_surface_variant"
        status = busyAction == "stop" and "Disconnecting…" or (busyAction == "switch" and "Switching profile…" or "Connecting…")
        sub = "Confirm the authentication prompt if asked"
    end

    local hero = {
        ui.label({text = status, fontSize = 20, fontWeight = "bold", color = color}),
    }
    if active and not transition then
        table.insert(hero, ui.label({text = state.managed and fmtDuration(state.uptime) or "Started outside panel", fontSize = 26, fontWeight = "bold"}))
    else
        table.insert(hero, ui.label({text = "--:--:--", fontSize = 26, fontWeight = "bold", color = "on_surface_variant/0.4"}))
    end
    table.insert(hero, ui.label({text = sub, fontSize = 12, color = "on_surface_variant", maxWidth = 340, maxLines = 2}))

    local fill = (leak and "error/0.12") or (active and "primary/0.10") or "surface_variant/0.4"
    local items = {header("VPN")}
    if banner() then table.insert(items, banner()) end
    local body = {}
    table.insert(body, ui.column({gap = 3, padding = 14, radius = 16, fill = fill, align = "center"}, hero))

    table.insert(body, ui.button({
        text = transition and "Please wait…" or (active and "Disconnect" or "Connect"),
        glyph = active and "power" or "shield-lock",
        variant = active and "secondary" or "primary",
        controlSize = "lg",
        onClick = "toggleVpn",
        enabled = not busy and state.installed == true and (active or #(state.profiles or {}) > 0),
    }))

    local chips = {
        chip(leak and "alert-triangle" or "network", active and (state.ipv6_disabled and "IPv4 only" or "IPv6 still on") or "System defaults", leak and "error" or nil),
        chip("server", state.server or "Loading…"),
    }
    table.insert(body, ui.row({gap = 8}, chips))

    table.insert(body, exitCard())

    table.insert(body, ui.row({align = "center", gap = 10, padding = 10, radius = 12, fill = "surface_variant/0.4"}, {
        ui.glyph({name = "list", size = 20, color = "on_surface_variant"}),
        ui.column({gap = 1, flexGrow = 1}, {
            ui.label({text = "Profile", fontSize = 11, color = "on_surface_variant"}),
            ui.label({text = state.profile or "None", fontSize = 15, fontWeight = "bold", maxWidth = 190, maxLines = 1}),
        }),
        ui.button({text = "Change", glyph = "chevron-right", variant = "outline", controlSize = "sm", onClick = "openProfiles", enabled = not busy}),
    }))

    table.insert(items, ui.scroll({flexGrow = 1, gap = 10}, body))
    table.insert(items, ui.row({gap = 6}, {
        ui.button({text = "Logs", glyph = "file-text", variant = "ghost", controlSize = "sm", onClick = "openLogs", flexGrow = 1}),
        ui.button({text = "Settings", glyph = "settings", variant = "ghost", controlSize = "sm", onClick = "openSettings", enabled = not busy and #(state.profiles or {}) > 0, flexGrow = 1}),
    }))
    if state.installed == false then
        table.insert(items, ui.button({text = "Install VPN controls", glyph = "download", variant = "primary", onClick = "installControls", enabled = not busy}))
    end
    return items
end

-- ───────────────────────── other pages ─────────────────────────

local function renderLogs()
    local lines = {}
    for line in string.gmatch(logs, "[^\r\n]+") do table.insert(lines, line) end
    local first = math.max(1, #lines - 220)
    local rows = {}
    for i = first, #lines do
        table.insert(rows, ui.label({text = lines[i], fontSize = 11, color = logColor(lines[i]), maxWidth = 365, maxLines = 4}))
    end
    return {header("Logs", "goBack"),
        ui.row({gap = 8}, {
            ui.button({text = "Refresh", glyph = "refresh", variant = "outline", controlSize = "sm", onClick = "openLogs", flexGrow = 1}),
            ui.button({text = "Open folder", glyph = "folder", variant = "ghost", controlSize = "sm", onClick = "openFolder", flexGrow = 1}),
        }),
        ui.scroll({flexGrow = 1, gap = 3, fill = "surface_variant/0.4", radius = 14, padding = 12}, rows),
    }
end

local function renderUpdates()
    return {header("Tool updates", "openSettings"),
        card({
            ui.row({justify = "space_between", align = "center"}, {
                ui.label({text = "Installed", fontSize = 12, color = "on_surface_variant"}),
                ui.label({text = updateInfo.installed_version or "Loading…", fontSize = 13, fontWeight = "bold"}),
            }),
            ui.row({justify = "space_between", align = "center"}, {
                ui.label({text = "Project version", fontSize = 12, color = "on_surface_variant"}),
                ui.label({text = updateInfo.source_version or "Unavailable", fontSize = 13, fontWeight = "bold"}),
            }),
            ui.label({text = updateInfo.available and (updateInfo.update_available and "Code or UI updates are available." or "Installed code matches the project source.") or "Project source is missing. Use vpn update /path/to/project.",
                fontSize = 13, color = updateInfo.update_available and "primary" or nil, maxWidth = 350, maxLines = 3}),
        }, {gap = 12, padding = 18}),
        ui.label({text = "Source: " .. (updateInfo.source or ""), fontSize = 11, color = "on_surface_variant", maxWidth = 375, maxLines = 4}),
        ui.label({text = "Updates keep profiles, backups and logs. The installer may ask for administrator authorization. No remote release server is used.", fontSize = 11, color = "on_surface_variant", maxWidth = 375, maxLines = 5}),
        ui.spacer({flexGrow = 1}),
        ui.row({gap = 8}, {
            ui.button({text = "Check", glyph = "refresh", variant = "outline", onClick = "openUpdates"}),
            ui.button({text = "Update", glyph = "download", variant = "primary", enabled = updateInfo.available == true, onClick = "launchUpdate", flexGrow = 1}),
        }),
    }
end

local function renderJson()
    return {header("Edit JSON", "openProfiles"),
        ui.label({text = jsonName .. " · contains private credentials", fontSize = 12, color = "on_surface_variant"}),
        ui.input({key = "profile-json-editor-" .. jsonRevision, value = jsonContent, multiline = true, flexGrow = 1, enabled = not busy,
            onChange = function(value) jsonContent = value end}),
        ui.label({text = "Keep the IPv4-only routing and the managed tunnel/listener. Changes apply on reconnect.", fontSize = 11, color = "on_surface_variant", maxWidth = 375, maxLines = 3}),
        ui.row({gap = 8}, {
            ui.button({text = "Cancel", variant = "ghost", onClick = "openProfiles", enabled = not busy}),
            ui.button({text = busy and "Validating…" or "Validate & save", glyph = "device-floppy", variant = "primary", flexGrow = 1, onClick = "saveJson", enabled = not busy}),
        }),
    }
end

local function renderProfiles()
    local items = {header("Profiles", "goBack")}
    if banner() then table.insert(items, banner()) end
    local rows = {}
    for _, name in ipairs(state.profiles or {}) do
        local chosen = name == state.profile
        local running = state.active and name == state.active_profile
        table.insert(rows, ui.button({key = name, text = name .. (running and "  ·  connected" or ""),
            glyph = chosen and "circle-check" or "circle", variant = chosen and "secondary" or "ghost", contentAlign = "start",
            enabled = not busy, onClick = function() profileAction("select", name) end}))
    end
    table.insert(items, ui.scroll({flexGrow = 1, gap = 6, fill = "surface_variant/0.35", radius = 14, padding = 8}, rows))
    if state.active and state.profile and state.profile ~= state.active_profile then
        table.insert(items, ui.button({text = "Switch & reconnect to " .. state.profile, glyph = "refresh", variant = "primary", controlSize = "lg", onClick = "reconnectNow", enabled = not busy}))
    else
        table.insert(items, ui.label({text = "Selecting a profile applies on the next connection.", fontSize = 11, color = "on_surface_variant"}))
    end
    table.insert(items, ui.row({gap = 6}, {
        ui.button({text = "Edit", glyph = "edit", variant = "outline", controlSize = "sm", onClick = "openSettings", enabled = not busy and state.profile ~= nil, flexGrow = 1}),
        ui.button({text = "Duplicate", glyph = "copy", variant = "ghost", controlSize = "sm", onClick = function() page = "duplicate"; newName = (state.profile or "profile") .. "-copy"; render() end, enabled = not busy, flexGrow = 1}),
        ui.button({text = "Rename", glyph = "pencil", variant = "ghost", controlSize = "sm", onClick = function() page = "rename"; newName = state.profile or ""; render() end, enabled = not busy, flexGrow = 1}),
    }))
    table.insert(items, ui.row({gap = 6}, {
        ui.button({text = "JSON", glyph = "code", variant = "ghost", controlSize = "sm", onClick = "openJson", enabled = not busy}),
        ui.button({text = "Delete", glyph = "trash", variant = "ghost", controlSize = "sm", onClick = function() page = "delete"; render() end, enabled = not busy}),
        ui.button({text = "Add profile", glyph = "plus", variant = "primary", flexGrow = 1, onClick = "openAdd", enabled = not busy}),
    }))
    return items
end

local function renderForm()
    local title = page == "add" and "Add profile" or (page == "duplicate" and "Duplicate profile" or "Rename profile")
    local items = {header(title, "openProfiles"),
        ui.label({text = "Profile name", fontSize = 12, color = "on_surface_variant"}),
        ui.input({key = "new-profile-name", value = newName, placeholder = "e.g. osg2", onChange = function(v) newName = v end, enabled = not busy}),
    }
    if page == "add" then
        table.insert(items, ui.label({text = "VLESS link or sing-box JSON file path", fontSize = 12, color = "on_surface_variant"}))
        table.insert(items, ui.input({key = "new-profile-source", value = newSource, password = true, placeholder = "Paste vless://… or /path/to/profile.json", onChange = function(v) newSource = v end, enabled = not busy}))
        table.insert(items, ui.label({text = "Supports VLESS with TLS over TCP or WebSocket. Imports use the IPv4-only routing template.", fontSize = 11, color = "on_surface_variant", maxWidth = 375, maxLines = 4}))
    end
    table.insert(items, ui.spacer({flexGrow = 1}))
    table.insert(items, ui.row({gap = 8}, {
        ui.button({text = "Cancel", variant = "ghost", onClick = "openProfiles", enabled = not busy}),
        ui.button({text = busy and "Saving…" or "Save profile", variant = "primary", flexGrow = 1, onClick = "saveProfile", enabled = not busy}),
    }))
    return items
end

local function renderDelete()
    return {header("Delete profile", "openProfiles"),
        ui.spacer({flexGrow = 1}),
        ui.column({gap = 10, padding = 20, radius = 18, fill = "error/0.10", align = "center"}, {
            ui.glyph({name = "trash", size = 36, color = "error"}),
            ui.label({text = "Delete “" .. (state.profile or "") .. "”?", fontSize = 18, fontWeight = "bold", maxWidth = 340, maxLines = 2}),
            ui.label({text = "A private recovery copy is kept. A connected profile cannot be deleted.", fontSize = 12, color = "on_surface_variant", maxWidth = 340, maxLines = 3}),
        }),
        ui.spacer({flexGrow = 1}),
        ui.row({gap = 8}, {
            ui.button({text = "Cancel", variant = "ghost", onClick = "openProfiles", enabled = not busy}),
            ui.button({text = "Delete profile", glyph = "trash", variant = "destructive", flexGrow = 1, onClick = function() profileAction("delete", state.profile) end, enabled = not busy}),
        }),
    }
end

local function renderSettings()
    local items = {header("Profile settings", "goBack")}
    if banner() then table.insert(items, banner()) end
    table.insert(items, ui.label({text = (fields.name or "Profile") .. " · changes apply when you reconnect", color = "on_surface_variant", fontSize = 12}))
    local labels = {{"server", "Server IPv4 or hostname"}, {"port", "Port"}, {"sni", "TLS server name"}, {"ws_host", "WebSocket host"}, {"ws_path", "WebSocket path"}}
    local form = {}
    local function option(text, value, handler)
        local chosen = (state.bar_label or "vpn") == value
        return ui.button({key = "bar-" .. value, text = text, variant = chosen and "secondary" or "ghost", selected = chosen,
            glyph = chosen and "circle-check" or "circle", controlSize = "sm", flexGrow = 1, onClick = handler})
    end
    table.insert(form, card({
        ui.label({text = "Top bar label", fontSize = 12, color = "on_surface_variant"}),
        ui.row({gap = 6}, {option("Icon only", "icon", "barLabelIcon"), option("VPN", "vpn", "barLabelVpn"), option("Profile", "profile", "barLabelProfile")}),
    }, {key = "bar-label-card"}))
    for _, entry in ipairs(labels) do
        local key, title = entry[1], entry[2]
        table.insert(form, ui.column({key = "field-" .. key, gap = 3}, {
            ui.label({text = title, fontSize = 12, color = "on_surface_variant"}),
            ui.input({key = "input-" .. key, value = tostring(fields[key] or ""), controlSize = "sm", enabled = not busy,
                onChange = function(value) fields[key] = value end}),
        }))
    end
    table.insert(form, ui.column({key = "field-uuid", gap = 3}, {
        ui.label({text = "Replace UUID (leave blank to keep)", fontSize = 12, color = "on_surface_variant"}),
        ui.input({key = "profile-uuid", value = "", password = true, enabled = not busy, controlSize = "sm", onChange = function(v) fields.uuid = v end}),
    }))
    table.insert(form, ui.row({justify = "space_between", align = "center", padding = 12, radius = 12, fill = "surface_variant/0.4"}, {
        ui.label({text = "Verify server certificate", fontSize = 13}),
        ui.toggle({checked = fields.tls_verify == true, enabled = not busy, onChange = function(v) fields.tls_verify = v == "true"; render() end}),
    }))
    table.insert(form, ui.button({text = "Tool updates", glyph = "download", variant = "ghost", onClick = "openUpdates"}))
    table.insert(form, ui.label({text = "IPv4 only is always enforced. Credentials stay unchanged.", maxWidth = 365, maxLines = 2, color = "on_surface_variant", fontSize = 11}))
    table.insert(items, ui.scroll({key = "settings-scroll", flexGrow = 1, gap = 8}, form))
    table.insert(items, ui.row({gap = 8}, {
        ui.button({text = "Back", variant = "ghost", onClick = "goBack", enabled = not busy}),
        ui.button({text = busy and "Saving…" or "Save settings", glyph = "device-floppy", variant = "primary", onClick = "saveSettings", enabled = not busy, flexGrow = 1}),
    }))
    return items
end

-- ───────────────────────── render + lifecycle ─────────────────────────

function render()
    local items
    if page == "logs" then items = renderLogs()
    elseif page == "updates" then items = renderUpdates()
    elseif page == "json" then items = renderJson()
    elseif page == "profiles" then items = renderProfiles()
    elseif page == "add" or page == "duplicate" or page == "rename" then items = renderForm()
    elseif page == "delete" then items = renderDelete()
    elseif page == "settings" then items = renderSettings()
    else items = renderMain() end
    local final = {}
    for _, item in ipairs(items) do
        if item then table.insert(final, item) end
    end
    if page ~= "main" and page ~= "profiles" and page ~= "settings" and notice ~= "" then
        table.insert(final, banner())
    end
    panel.render(ui.column({key = "page-" .. page, gap = 10, padding = 4, flexGrow = 1}, final))
end

local function request(action, extra, callback)
    local argv = {"python3", controller, action}
    if extra then
        local dir = noctalia.pluginDataDir()
        local path = dir .. "/request-" .. tostring(os.time()) .. "-" .. tostring(math.random(100000, 999999)) .. ".json"
        if not noctalia.writeFile(path, extra) then
            callback({error = "Could not save private request."}, false)
            return
        end
        table.insert(argv, path)
    end
    noctalia.runAsync(argv, function(result)
        local ok, data = pcall(noctalia.json.decode, result.stdout)
        if not ok or type(data) ~= "table" then data = {error = result.stderr ~= "" and result.stderr or "Could not read VPN response."} end
        callback(data, result.exitCode == 0)
    end)
end

function refresh()
    if refreshing then return end
    refreshing = true
    request("status", nil, function(data, ok)
        refreshing = false
        if ok then
            state = data
            if data.check then
                lastCheck = data.check
                lastCheckKey = tostring(data.active) .. ":" .. tostring(data.invocation)
            end
            updateLive()
            -- one automatic check per connection, as soon as the tunnel is up
            if state.active and not busy and not checkBusy and lastCheck == nil and autoCheckedFor ~= state.invocation then
                autoCheckedFor = state.invocation
                runCheck(true)
            end
        else
            setNotice(data.error, true)
        end
        render()
    end)
end

function runCheck(silent)
    if checkBusy then return end
    checkBusy = true
    render()
    request("check", nil, function(data, ok)
        checkBusy = false
        if data.checked_at then
            lastCheck = data
            lastCheckKey = tostring(state.active) .. ":" .. tostring(state.invocation)
        else
            lastCheck = {ok = false, error = data.error or "Check failed", checked_at = os.time()}
            lastCheckKey = tostring(state.active) .. ":" .. tostring(state.invocation)
        end
        if not silent then
            if data.ok then setNotice("HTTPS connection verified.", false)
            else setNotice(data.error or "Check failed", true) end
        end
        refresh()
    end)
end

function onOpen()
    page = "main"
    notice = ""
    render()
    refresh()
end

function update()
    if notice ~= "" and not errorMessage and os.time() - noticeAt > 6 then
        notice = ""
    end
    if page == "main" then refresh() end
end

function closePanel() panel.close() end
function goBack() page = "main"; notice = ""; refresh() end

function toggleVpn()
    if busy then return end
    busy = true
    busyAction = state.active and "stop" or "start"
    setNotice("", false)
    render()
    request(busyAction, nil, function(data, ok)
        busy = false
        busyAction = nil
        setNotice(ok and (data.message or "Done") or data.error, not ok)
        refresh()
    end)
end

function reconnectNow()
    if busy then return end
    busy = true
    busyAction = "switch"
    page = "main"
    setNotice("", false)
    render()
    request("restart", nil, function(data, ok)
        busy = false
        busyAction = nil
        setNotice(ok and "Switched profile." or data.error, not ok)
        refresh()
    end)
end

function checkNow() runCheck(false) end

local function setBarLabel(value)
    state.bar_label = value
    render()
    request("set-ui", noctalia.json.encode({bar_label = value}), function(data, ok)
        if not ok then setNotice(data.error or "Could not save the label setting.", true) end
        refresh()
    end)
end
function barLabelIcon() setBarLabel("icon") end
function barLabelVpn() setBarLabel("vpn") end
function barLabelProfile() setBarLabel("profile") end

function copyIp()
    if not (lastCheck and lastCheck.ip and lastCheck.ip ~= "") then return end
    noctalia.runAsync({"wl-copy", lastCheck.ip}, function(result)
        if result.exitCode == 0 then setNotice("Exit IP copied.", false)
        else setNotice("Copy failed. Install wl-clipboard (wl-copy).", true) end
        render()
    end)
end

function openLogs()
    page = "logs"
    logs = "Loading logs…"
    render()
    noctalia.runAsync({"python3", controller, "logs"}, function(result)
        logs = result.stdout ~= "" and result.stdout or result.stderr
        render()
    end)
end

function openFolder()
    noctalia.runAsync({"xdg-open", noctalia.expandPath("~/.local/state/raze-vpn/logs")})
end

function openSettings()
    request("settings", nil, function(data, ok)
        if ok then fields = data; page = "settings"; notice = "" else setNotice(data.error, true) end
        render()
    end)
end

function saveSettings()
    busy = true
    busyAction = "save"
    render()
    request("save-settings", noctalia.json.encode(fields), function(data, ok)
        busy = false
        busyAction = nil
        setNotice(ok and data.message or data.error, not ok)
        render()
    end)
end

function installControls()
    noctalia.runInTerminal("bash ~/Projects/raze-vpn/setup.sh")
end

function openProfiles()
    page = "profiles"
    notice = ""
    refresh()
end

function openAdd()
    newName = ""
    newSource = ""
    page = "add"
    notice = ""
    render()
end

function profileAction(operation, name, value)
    busy = true
    busyAction = "save"
    render()
    request("profile-request", noctalia.json.encode({operation = operation, name = name, value = value}), function(data, ok)
        busy = false
        busyAction = nil
        setNotice(ok and data.message or data.error, not ok)
        if ok then page = "profiles" end
        refresh()
    end)
end

function saveProfile()
    if page == "add" then
        profileAction("add", newName, newSource)
    elseif page == "duplicate" then
        profileAction("duplicate", state.profile, newName)
    elseif page == "rename" then
        profileAction("rename", state.profile, newName)
    end
end

function onIpc(event)
    if event == "profiles" then openProfiles()
    elseif event == "settings" then openSettings()
    elseif event == "updates" then openUpdates()
    elseif event == "json" then openJson()
    elseif event == "logs" then openLogs()
    elseif event == "check" then checkNow()
    end
end

function openJson()
    request("json-settings", nil, function(data, ok)
        if ok then
            jsonContent = data.content
            jsonRevision = data.revision
            jsonName = data.name
            page = "json"
            notice = ""
        else setNotice(data.error, true) end
        render()
    end)
end

function saveJson()
    profileAction("edit-json", jsonName, {content = jsonContent, revision = jsonRevision})
end

function openUpdates()
    page = "updates"
    notice = ""
    request("updates", nil, function(data, ok)
        if ok then updateInfo = data else setNotice(data.error, true) end
        render()
    end)
end

function launchUpdate()
    request("launch-update", nil, function(data, ok)
        setNotice(ok and data.message or data.error, not ok)
        render()
    end)
end
