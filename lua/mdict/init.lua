local M = {}

local config = {
    mdx_path = "",
    mdd_path = "",
    python_cmd = "python3",
    max_width = 80,
    max_height = 30,
}

local scripts_dir = vim.fn.fnamemodify(debug.getinfo(1, "S").source:sub(2), ":h:h:h")
    .. "/scripts/"
local script_path = scripts_dir .. "mdict_lookup.py"
local online_script_path = scripts_dir .. "mdict_online.py"

local float_win = nil
local float_buf = nil

-- Each section: { name = "O2", lines = { ... }, collapsed = false }
local sections = {}

-- History stack: each entry is { word = "...", sections = { ... } }
local history = {}

local ns = vim.api.nvim_create_namespace("mdict")

local function setup_highlights()
    local set_hl = vim.api.nvim_set_hl
    set_hl(0, "MdictDictName", { default = true, link = "Title" })
    set_hl(0, "MdictDivider",  { default = true, link = "NonText" })
    set_hl(0, "MdictHeadword", { default = true, bold = true, fg = "#e0af68" })
    set_hl(0, "MdictPos",      { default = true, link = "Type" })
    set_hl(0, "MdictPron",     { default = true, link = "String" })
    set_hl(0, "MdictSection",  { default = true, link = "Keyword" })
    set_hl(0, "MdictDefNum",   { default = true, link = "Number" })
    set_hl(0, "MdictDef",      { default = true, fg = "#c0caf5" })
    set_hl(0, "MdictExample",  { default = true, italic = true, fg = "#565f89" })
    set_hl(0, "MdictBox",      { default = true, link = "WarningMsg" })
    set_hl(0, "MdictPhrasal",  { default = true, link = "Special" })
    set_hl(0, "MdictSynonym",  { default = true, link = "Constant" })
end

local function apply_highlights(buf, lines)
    vim.api.nvim_buf_clear_namespace(buf, ns, 0, -1)
    local expect_headword = false

    for i, line in ipairs(lines) do
        local row = i - 1

        if line:find("^▼") or line:find("^▶") then
            vim.api.nvim_buf_add_highlight(buf, ns, "MdictDictName", row, 0, -1)
            expect_headword = true

        elseif line:find("^─") then
            vim.api.nvim_buf_add_highlight(buf, ns, "MdictDivider", row, 0, -1)

        elseif expect_headword and line ~= "" then
            expect_headword = false
            local paren_pos = line:find("  %(")
            local phon_pos = line:find("  /")
            if paren_pos then
                vim.api.nvim_buf_add_highlight(buf, ns, "MdictHeadword", row, 0, paren_pos - 1)
                vim.api.nvim_buf_add_highlight(buf, ns, "MdictPos", row, paren_pos + 1, -1)
            elseif phon_pos then
                vim.api.nvim_buf_add_highlight(buf, ns, "MdictHeadword", row, 0, phon_pos - 1)
                vim.api.nvim_buf_add_highlight(buf, ns, "MdictPron", row, phon_pos + 1, -1)
            else
                vim.api.nvim_buf_add_highlight(buf, ns, "MdictHeadword", row, 0, -1)
            end

        elseif line:match("^%S") and line:find("/") then
            vim.api.nvim_buf_add_highlight(buf, ns, "MdictPron", row, 0, -1)

        elseif line:find("━━") then
            vim.api.nvim_buf_add_highlight(buf, ns, "MdictSection", row, 0, -1)

        elseif line:find("◆") then
            vim.api.nvim_buf_add_highlight(buf, ns, "MdictExample", row, 0, -1)

        elseif line:find("┌─") then
            vim.api.nvim_buf_add_highlight(buf, ns, "MdictBox", row, 0, -1)

        elseif line:find("●") then
            vim.api.nvim_buf_add_highlight(buf, ns, "MdictPhrasal", row, 0, -1)

        elseif line:match("^%s+SYN:") or line:match("^%s+ANT:") then
            vim.api.nvim_buf_add_highlight(buf, ns, "MdictSynonym", row, 0, -1)

        elseif line:match("^%s+%d+%.%s") then
            local s, e = line:find("%d+%.")
            if s then
                vim.api.nvim_buf_add_highlight(buf, ns, "MdictDefNum", row, s - 1, e)
                vim.api.nvim_buf_add_highlight(buf, ns, "MdictDef", row, e, -1)
            end
        end
    end
end

local function close_float()
    if float_win and vim.api.nvim_win_is_valid(float_win) then
        vim.api.nvim_win_close(float_win, true)
    end
    if float_buf and vim.api.nvim_buf_is_valid(float_buf) then
        vim.api.nvim_buf_delete(float_buf, { force = true })
    end
    float_win = nil
    float_buf = nil
end

local function render_sections()
    local buf_lines = {}
    local header_line_map = {}
    for i, sec in ipairs(sections) do
        if i > 1 then
            table.insert(buf_lines, "")
            table.insert(buf_lines, "────────────────────────────────")
        end
        local marker = sec.collapsed and "▶" or "▼"
        table.insert(buf_lines, marker .. " 【" .. sec.name .. "】")
        header_line_map[#buf_lines] = i
        if not sec.collapsed then
            table.insert(buf_lines, "")
            for _, line in ipairs(sec.lines) do
                table.insert(buf_lines, line)
            end
        end
    end
    return buf_lines, header_line_map
end

local function find_section_for_line(lnum, header_line_map)
    local headers_sorted = {}
    for hl, si in pairs(header_line_map) do
        table.insert(headers_sorted, { line = hl, sec = si })
    end
    table.sort(headers_sorted, function(a, b) return a.line < b.line end)

    local sec_idx = nil
    for _, h in ipairs(headers_sorted) do
        if lnum >= h.line then
            sec_idx = h.sec
        else
            break
        end
    end
    return sec_idx
end

local current_header_line_map = {}

local function deep_copy_sections(secs)
    local copy = {}
    for _, sec in ipairs(secs) do
        local lines_copy = {}
        for _, l in ipairs(sec.lines) do
            table.insert(lines_copy, l)
        end
        table.insert(copy, { name = sec.name, lines = lines_copy, collapsed = sec.collapsed })
    end
    return copy
end

local function open_float(title)
    close_float()

    local buf_lines, header_line_map = render_sections()
    current_header_line_map = header_line_map

    local width = 0
    for _, line in ipairs(buf_lines) do
        width = math.max(width, vim.fn.strdisplaywidth(line))
    end
    width = math.min(width + 2, config.max_width)
    local height = math.min(#buf_lines, config.max_height)

    local editor_w = vim.o.columns
    local editor_h = vim.o.lines - 2
    local col = math.floor((editor_w - width) / 2)
    local row = math.floor((editor_h - height) / 2)

    float_buf = vim.api.nvim_create_buf(false, true)
    vim.api.nvim_buf_set_lines(float_buf, 0, -1, false, buf_lines)
    apply_highlights(float_buf, buf_lines)
    vim.bo[float_buf].modifiable = false
    vim.bo[float_buf].bufhidden = "wipe"

    float_win = vim.api.nvim_open_win(float_buf, true, {
        relative = "editor",
        width = width,
        height = height,
        col = col,
        row = row,
        style = "minimal",
        border = "rounded",
        title = " " .. title .. " ",
        title_pos = "center",
    })
    vim.wo[float_win].wrap = true
    vim.wo[float_win].linebreak = true
    vim.wo[float_win].conceallevel = 2

    -- q: close entirely
    vim.keymap.set("n", "q", function()
        history = {}
        close_float()
    end, { buffer = float_buf, nowait = true })

    -- Esc: go back or close if no history
    vim.keymap.set("n", "<Esc>", function()
        if #history > 0 then
            local prev = table.remove(history)
            sections = prev.sections
            open_float(prev.word)
        else
            close_float()
        end
    end, { buffer = float_buf, nowait = true })

    -- L: look up word under cursor, push current to history
    vim.keymap.set("n", "L", function()
        local cword = vim.fn.expand("<cword>")
        if cword ~= "" then
            table.insert(history, { word = title, sections = deep_copy_sections(sections) })
            M.lookup(cword)
        end
    end, { buffer = float_buf, nowait = true })

    -- J: toggle section collapse
    vim.keymap.set("n", "J", function()
        if not float_win or not vim.api.nvim_win_is_valid(float_win) then
            return
        end
        local cursor_lnum = vim.api.nvim_win_get_cursor(float_win)[1]
        local buf_lines_now, hlm = render_sections()
        current_header_line_map = hlm
        local sec_idx = find_section_for_line(cursor_lnum, current_header_line_map)
        if sec_idx and sections[sec_idx] then
            sections[sec_idx].collapsed = not sections[sec_idx].collapsed
            local new_lines, new_hlm = render_sections()
            current_header_line_map = new_hlm
            local target_lnum = 1
            for hl, si in pairs(new_hlm) do
                if si == sec_idx then
                    target_lnum = hl
                    break
                end
            end
            vim.bo[float_buf].modifiable = true
            vim.api.nvim_buf_set_lines(float_buf, 0, -1, false, new_lines)
            apply_highlights(float_buf, new_lines)
            vim.bo[float_buf].modifiable = false

            local w = 0
            for _, line in ipairs(new_lines) do
                w = math.max(w, vim.fn.strdisplaywidth(line))
            end
            w = math.min(w + 2, config.max_width)
            local h = math.min(#new_lines, config.max_height)
            vim.api.nvim_win_set_config(float_win, { width = w, height = h })
            vim.api.nvim_win_set_cursor(float_win, { target_lnum, 0 })
        end
    end, { buffer = float_buf, nowait = true })
end

local function get_mdx_paths()
    local paths = config.mdx_path
    if type(paths) == "string" then
        if paths == "" then
            return {}
        end
        return { paths }
    end
    return paths
end

function M.lookup(word)
    word = word or vim.fn.expand("<cword>")
    if word == "" then
        vim.notify("No word under cursor", vim.log.levels.WARN)
        return
    end

    local mdx_paths = get_mdx_paths()
    if #mdx_paths == 0 then
        vim.notify("mdict: mdx_path not configured. Call require('mdict').setup({ mdx_path = '...' })",
            vim.log.levels.ERROR)
        return
    end

    sections = {}
    for _, mdx in ipairs(mdx_paths) do
        if vim.fn.filereadable(mdx) == 0 then
            vim.notify("mdict: dictionary not found: " .. mdx, vim.log.levels.WARN)
            goto continue
        end

        local cmd = string.format(
            "%s %s --mdx %s --word %s",
            vim.fn.shellescape(config.python_cmd),
            vim.fn.shellescape(script_path),
            vim.fn.shellescape(mdx),
            vim.fn.shellescape(word)
        )
        local output = vim.fn.system(cmd)
        if vim.v.shell_error == 0 and output ~= "" then
            local dict_name = vim.fn.fnamemodify(mdx, ":t:r")
            local lines = vim.split(output, "\n", { trimempty = true })
            table.insert(sections, { name = dict_name, lines = lines, collapsed = false })
        end

        ::continue::
    end

    if #sections == 0 then
        local online_cmd = string.format(
            "%s %s %s",
            vim.fn.shellescape(config.python_cmd),
            vim.fn.shellescape(online_script_path),
            vim.fn.shellescape(word)
        )
        local online_output = vim.fn.system(online_cmd)
        if vim.v.shell_error == 0 and online_output ~= "" then
            local lines = vim.split(online_output, "\n", { trimempty = true })
            table.insert(sections, { name = "Online", lines = lines, collapsed = false })
        end
    end

    if #sections == 0 then
        vim.notify("No definition found for: " .. word, vim.log.levels.INFO)
        return
    end

    open_float(word)
end

function M.setup(opts)
    config = vim.tbl_deep_extend("force", config, opts or {})
    setup_highlights()
end

return M
