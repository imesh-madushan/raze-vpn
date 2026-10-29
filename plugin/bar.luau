local pending = false
local state = {}
local previous = nil          -- last known active flag (nil until first poll)
local previousState = nil
local warnedLeak = false
local controller = noctalia.expandPath("~/.local/share/raze-vpn/app/controller.py")
noctalia.setUpdateInterval(3000)

local function shortUptime(seconds)
    seconds = tonumber(seconds) or 0
    if seconds < 60 then return seconds .. "s" end
    if seconds < 3600 then return math.floor(seconds / 60) .. "m" end
    return string.format("%dh %02dm", math.floor(seconds / 3600), math.floor(seconds / 60) % 60)
end

local function announce(message)
    noctalia.notify("raze VPN", message)
end

local function transitions()
    -- the very first poll only records the current state; it never notifies
    if previous ~= nil then
        if state.active and not previous then
            local profile = (state.active_profile or "") ~= "" and (" · " .. state.active_profile) or ""
            announce("Connected" .. profile .. ". Public IPv4 traffic uses the VPN.")
        elseif previous and not state.active then
            announce("Disconnected. Normal networking and IPv6 settings restored.")
        end
        if state.state == "failed" and previousState ~= "failed" and not state.active then
            announce("VPN failed to start. Open the panel and check Logs.")
        end
    end
    if state.active and state.ipv6_disabled == false then
        if not warnedLeak then
            warnedLeak = true
            announce("Warning: VPN is up but IPv6 is still enabled. Traffic may leak.")
        end
    else
        warnedLeak = false
    end
    previous = state.active == true
    previousState = state.state
end

function update()
    if pending then return end
    pending = true
    noctalia.runAsync({"python3", controller, "status"}, function(result)
        pending = false
        if result.exitCode ~= 0 then
            barWidget.setText("VPN ?")
            barWidget.setGlyph("shield-exclamation")
            barWidget.setColor("error")
            barWidget.setTooltip("VPN status unavailable. Click to inspect.")
            return
        end
        local ok, value = pcall(noctalia.json.decode, result.stdout)
        if not ok or type(value) ~= "table" then return end
        state = value
        transitions()

        local leak = state.active and not state.ipv6_disabled
        local failed = (not state.active) and state.state == "failed"
        local color = "on_surface_variant"
        local glyph = "shield-off"
        if state.active then color, glyph = "primary", "shield-lock" end
        if leak or failed then color, glyph = "error", "shield-exclamation" end

        -- label is a user setting (panel -> Settings -> Top bar label)
        local text = "VPN"
        if state.bar_label == "icon" then
            text = ""
        elseif state.bar_label == "profile" then
            local name = (state.active_profile or "") ~= "" and state.active_profile or state.profile
            text = (name and name ~= "") and name or "VPN"
        end
        barWidget.setText(text)
        barWidget.setGlyph(glyph)
        barWidget.setColor(color)
        barWidget.setGlyphColor(color)

        local lines = {"raze VPN"}
        if state.active then
            table.insert(lines, "Connected" .. ((state.active_profile or "") ~= "" and (" · " .. state.active_profile) or "") .. (leak and " · IPv6 ON (leak risk)" or " · IPv4 only"))
            table.insert(lines, "Session " .. shortUptime(state.uptime))
        elseif failed then
            table.insert(lines, "Failed to start · see Logs")
        else
            table.insert(lines, "Disconnected · normal networking")
        end
        table.insert(lines, "Click for controls · Right-click to connect/disconnect")
        barWidget.setTooltip(table.concat(lines, "\n"))
    end)
end

function onClick()
    noctalia.togglePanel("raze/vpn:panel")
end

function onRightClick()
    noctalia.runAsync({"python3", controller, state.active and "stop" or "start"}, function(result)
        if result.exitCode ~= 0 then
            noctalia.notify("raze VPN", "Could not change connection. Open the VPN panel for details.")
        end
        update()
    end)
end

update()
