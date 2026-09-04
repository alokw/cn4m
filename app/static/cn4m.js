// cn4m.js
// Frontend logic for the cn4m asset conformance tool.
// Handles AJAX calls to the Flask backend, Celery task progress polling, and
// the Tabulator review table (columns, QC formatting, selection).


// ── QC config ─────────────────────────────────────────────────────────────────
// Fetched once at page load from /qc_config. Used during table rendering to
// highlight cells that fail codec or resolution checks.

let qc_config = { codecs: [], resolutions: {}, fps: [] };


// ── Review table state ────────────────────────────────────────────────────────
// The Tabulator instance is the single source of truth for scan data: rows hold
// the asset objects, so selection, sorting, filtering and row removal all read
// from the table rather than scraping values back out of the rendered cells.
// Created on the first completed scan, reused (via replaceData) on every scan
// after that.

let asset_table = null;

// Whether the "QC fails only" toggle is engaged. Kept as a programmatic filter
// (addFilter/removeFilter), which ANDs with the header filters rather than
// replacing them, so the toggle and the column filters compose.
let qc_filter_active = false;

// localStorage key for the persisted column layout and sort. Bump the version
// suffix whenever asset_columns() changes shape, so an old saved layout can't
// mis-size or hide a newly added column.
// -v2: bumped when the version conflict column was added at the far left. A
// persisted -v1 layout knows nothing about it, and Tabulator appends unknown
// columns to the end — which would bury the caution icon off the right edge.
const PERSISTENCE_ID = "cn4m-review-v2";

// The read-only REPO / QUARANTINE tables, built lazily the first time their tab
// is opened. Same columns and machinery as the review table — see
// create_asset_table, which all three go through.
let browse_tables = { repo: null, quarantine: null };

// Transcode can be started from three tabs, but they all POST to the same
// endpoint — so update_progress can't tell them apart from the URL. Whoever
// starts a run records where its progress text should go.
let transcode_progress_destination = "#review_asset_progress";

// The internal keys stay repo/quarantine — they map straight onto the
// *_repo_assets / *_quar_assets buckets in assets.json and the /assets/<bucket>
// route. These are just what the user sees.
const BROWSE_LABELS = { repo: "approved", quarantine: "quarantined" };

// Extension groups, shared by the file-type icons and the audio-selection
// helpers. Compared lowercase with any leading dot stripped.
const AUDIO_EXTS = ["wav", "aiff", "aif", "mp3", "flac", "ogg", "m4a", "aac", "wma"];
const IMAGE_EXTS = ["png", "jpeg", "jpg", "tiff", "tif", "tga", "exr", "bmp", "gif", "webp", "dpx", "heic"];
const VIDEO_EXTS = ["mov", "mkv", "mp4", "avi", "webm", "m4v", "wmv", "flv", "mpg", "mpeg"];

function normalize_ext(ext) {
  return String(ext || "").toLowerCase().replace(/^\./, '');
}

function is_audio_ext(ext) {
  return AUDIO_EXTS.includes(normalize_ext(ext));
}

// Escape values that get interpolated into formatter HTML. Filenames and folder
// names are user-supplied, so a stray < or & must not be parsed as markup.
function escape_html(value) {
  return String(value === null || value === undefined ? "" : value)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function load_qc_config() {
  $.getJSON('/qc_config', function(data) {
    qc_config = data;
  });
}

// Resolution rules that apply to a file: the global (untagged) rules from
// QC_RESOLUTION plus this screen's rule, if one is configured.
function qc_resolution_rules(screen) {
  const res = qc_config.resolutions;
  if (!res) return [];
  const rules = (res.global || []).slice();
  const screen_rule = (res.screens || {})[(screen || "").trim().toLowerCase()];
  if (screen_rule) rules.push(screen_rule);
  return rules;
}

// Passing any one rule outright passes the file; otherwise the closest rule
// decides which dimension(s) get flagged, so a 1920x1920 file checked against
// 1920x1080 flags only the height.
function qc_resolution_fails(rules, width, height) {
  const w = width === "" || width === null || width === undefined ? null : parseInt(width);
  const h = height === "" || height === null || height === undefined ? null : parseInt(height);
  if (!rules.length || (w === null && h === null) || isNaN(w) || isNaN(h)) return { w: false, h: false };

  let best = { w: true, h: true };
  for (const rule of rules) {
    const w_fail = w !== null && w !== rule.w;
    const h_fail = h !== null && h !== rule.h;
    if (!w_fail && !h_fail) return { w: false, h: false };
    if (w_fail + h_fail < best.w + best.h) best = { w: w_fail, h: h_fail };
  }
  return best;
}

// ── cn4m suite rail ───────────────────────────────────────────────────────────
// The suite's other tools, each served on its own port (see "The cn4m suite" in
// the README). The port is the whole address: every link is built against
// window.location.hostname, so opening cn4m on the NAS from a laptop yields
// links to the tools ON THE NAS. A hardcoded localhost would instead point them
// back at whatever machine the browser is running on, which is a confusing way
// to fail — the links would look fine and quietly go nowhere.
//
// Adding a tool to the rail is one line here. "current" marks the app doing the
// rendering, which reads as a "you are here" rather than a link; it's declared
// rather than detected from location.port so the rail still marks itself
// correctly if cn4m is ever fronted by a reverse proxy on 80/443.
const SUITE_TOOLS = [
  { name: "cn4m",      port: 2640, current: true },
  { name: "inbound",   port: 2645 },
  { name: "smartsync", port: 2646 },
  { name: "symmetry",  port: 2647 },
  { name: "cascade",   port: 2649 },
];

function render_suite_rail() {
  const links = SUITE_TOOLS.map(function(tool) {
    if (tool.current) {
      return '<span class="obx-suite-current">' + escape_html(tool.name) + '</span>';
    }
    const url = window.location.protocol + "//" + window.location.hostname + ":" + tool.port + "/";
    // New tab on purpose: switching tools shouldn't discard a review in progress.
    return '<a href="' + escape_html(url) + '" target="_blank" rel="noopener">'
      + escape_html(tool.name) + '</a>';
  });
  $('#suite-links').html(links.join('<span class="obx-suite-sep">·</span>'));
  set_app_status("Ready");
}

// The status line at the right of the suite rail. Deliberately NOT a second home
// for task progress — each pane already has its own progress text, and a status
// bar that echoes them is just noise. This is for app-level state those can't
// show: what's still waiting, what can't be reached.
// level: "idle" (the default), "working", or "error" — it colours the dot.
function set_app_status(text, level) {
  const message = text || "";
  $('#app-status-text').text(message).attr('title', message);
  const dot = $('#app-status-dot').removeClass('obx-status-working obx-status-error');
  if (level === "working") dot.addClass('obx-status-working');
  if (level === "error") dot.addClass('obx-status-error');
}


// ── Button handlers ───────────────────────────────────────────────────────────
// These are wired up to the buttons in index.html via $(function() { ... }) at
// the bottom of that file.

function check_assets() {
  ajax_post_simple('/check_assets')
}

function approve_assets() {
  selected_assets = get_selected_assets()
  if (!selected_assets.length) return;
  ajax_post_with_selection('/approve_assets', selected_assets)
  remove_assets_from_table(selected_assets)  // optimistically remove rows while the task runs
  reveal_track_pane()  // there is now something worth pushing to the sheet
}

function quarantine_assets() {
  selected_assets = get_selected_assets()
  if (!selected_assets.length) return;
  ajax_post_with_selection('/quarantine_assets', selected_assets)
  remove_assets_from_table(selected_assets)  // optimistically remove rows while the task runs
  reveal_track_pane()  // quarantined assets get pushed to the sheet too
}

function track_assets() {
  ajax_post_simple('/track_assets')
}


// ── Preset loader ─────────────────────────────────────────────────────────────
// Fetches the available ffmpeg presets from the backend and populates the dropdown.

function load_ffmpeg_presets() {
  $.getJSON('/ffmpeg_presets', function(presets) {
    // One dropdown per tab that can transcode — all share .obx-preset-select
    $('.obx-preset-select').each(function() {
      var $select = $(this);
      $select.find('option:not(:first)').remove();
      $.each(presets, function(i, preset) {
        $select.append($('<option>', { value: preset.name, text: preset.label }));
      });
    });
  });
}


// ── Transcode ─────────────────────────────────────────────────────────────────

function transcode_assets() {
  var selected = get_selected_assets();
  if (selected.length === 0) {
    alert('Please select at least one asset.');
    return;
  }
  var preset_name = $('#ffmpeg-preset-select').val();
  if (!preset_name) {
    alert('Please select a preset.');
    return;
  }
  transcode_progress_destination = "#review_asset_progress";
  ajax_post_transcode('/transcode_assets', selected, preset_name);
  if (asset_table) asset_table.deselectRow();
}

function quarantine_and_transcode() {
  var selected = get_selected_assets();
  if (selected.length === 0) {
    alert('Please select at least one asset.');
    return;
  }
  var preset_name = $('#ffmpeg-preset-select').val();
  if (!preset_name) {
    alert('Please select a preset.');
    return;
  }
  transcode_progress_destination = "#review_asset_progress";
  ajax_post_transcode('/quarantine_and_transcode', selected, preset_name);
  if (asset_table) asset_table.deselectRow();
  remove_assets_from_table(selected);
  reveal_track_pane();
}


// ── Progress routing ──────────────────────────────────────────────────────────
// Routes the progress update to the correct handler based on which endpoint
// triggered the task (determined by parsing the status_task URL).

function update_progress(status_task, status_url) {
  console.log(status_task)

  // Strip any leading slashes and grab the first path segment (e.g. "check_assets")
  const parts = status_task.replace(/^\/+/, '').split('/');
  const basePath = parts[0];

  switch(basePath) {
    case "approve_assets":
      msg_destination = "#review_asset_progress"
      msg_pending = "Starting Approval"
      msg_progress = "Approving Assets"
      msg_complete = "Approval Complete"
      get_update_progress_feedback(status_task, status_url, msg_destination, msg_pending, msg_progress, msg_complete)
      break;

    case "quarantine_assets":
      msg_destination = "#review_asset_progress"
      msg_pending = "Starting Quarantine"
      msg_progress = "Quarantining Assets"
      msg_complete = "Quarantine Complete"
      get_update_progress_feedback(status_task, status_url, msg_destination, msg_pending, msg_progress, msg_complete)
      break;

    case "track_assets":
      msg_destination = "#track_assets_progress"
      msg_pending = "Connecting to Google Sheet"
      msg_progress = "Tracking Assets"
      msg_complete = "Assets Pushed to Tracker"
      get_update_progress_feedback(status_task, status_url, msg_destination, msg_pending, msg_progress, msg_complete)
      break;

    case "check_assets":
      // check_assets has its own handler because it also builds the results table
      handle_check_assets_progress(status_task, status_url);
      break;

    case "transcode_assets":
      msg_destination = transcode_progress_destination
      msg_pending = "Starting Transcode"
      msg_progress = "Transcoding"
      msg_complete = transcode_progress_destination === "#review_asset_progress"
        ? "Transcode Complete - <a href=\"#\" onclick=\"check_assets()\">Click to Re-Check Assets</a>"
        : "Transcode Complete"
      get_update_progress_feedback(status_task, status_url, msg_destination, msg_pending, msg_progress, msg_complete)
      break;

    case "quarantine_and_transcode":
      msg_destination = "#review_asset_progress"
      msg_pending = "Starting Quarantine & Transcode"
      msg_progress = "Processing"
      msg_complete = "Quarantine & Transcode Complete - <a href=\"#\" onclick=\"check_assets()\">Click to Re-Check Assets</a>"
      get_update_progress_feedback(status_task, status_url, msg_destination, msg_pending, msg_progress, msg_complete)
      break;
  }
}


// ── Review table (Tabulator) ──────────────────────────────────────────────────
// Column definitions, formatters and sorters for the asset review table.
// Formatters only affect *display*; sorting and filtering always run against the
// underlying row data, which is why the raw size_bytes / duration_ms fields exist.

// Red, tooltipped cell for a value that fails a QC rule.
function qc_span(value, expected) {
  return `<span class="qc-fail" title="Expected: ${escape_html(expected)}">${escape_html(value)}</span>`;
}

// Sort on a raw numeric field (size_bytes / duration_ms) while the column shows
// its human-readable twin. Assets missing the field — images have no duration,
// and entries scanned before those fields existed have neither — group at the
// ascending end instead of throwing.
function raw_number_sorter(field) {
  return function(a, b, aRow, bRow) {
    const av = Number(aRow.getData()[field]);
    const bv = Number(bRow.getData()[field]);
    const a_missing = !isFinite(av);
    const b_missing = !isFinite(bv);
    if (a_missing && b_missing) return 0;
    if (a_missing) return -1;
    if (b_missing) return 1;
    return av - bv;
  };
}

// Screen / Stem sorts audio files as a block ahead of everything else, then
// alphabetically within each block (Tabulator flips the result for descending).
function screen_sorter(a, b, aRow, bRow) {
  const a_audio = is_audio_ext(aRow.getData().extension);
  const b_audio = is_audio_ext(bRow.getData().extension);
  if (a_audio !== b_audio) return a_audio ? -1 : 1;
  return String(a || "").localeCompare(String(b || ""));
}

// Folder — spaces preserved so folder names don't visually collapse.
function folder_formatter(cell) {
  return escape_html(cell.getValue()).replace(/ /g, "&nbsp;");
}

// Name — prefixed with an audio/image/video icon when the extension is known.
function name_formatter(cell) {
  const ext = cell.getData().extension || "";
  const icon = get_file_type_icon(ext);
  const name = escape_html(cell.getValue());
  if (!icon) return name;
  return `<img src="/static/icons/${icon}" alt="${escape_html(ext)}" title="${escape_html(ext)}" class="cell-icon"> ${name}`;
}

// Version — green up-arrow when the basename matches an existing tracked or
// untracked asset, orange plus when it is brand new.
function version_formatter(cell) {
  const up = cell.getData().is_version_up;
  const icon = up ? "version_up.svg" : "new_file.svg";
  const alt = up ? "version up" : "new file";
  const title = up
    ? "version up — basename matches an existing tracked/untracked asset"
    : "new file — no matching basename in existing assets";
  return `<img src="/static/icons/${icon}" alt="${alt}" title="${title}" class="cell-icon"> ${escape_html(cell.getValue())}`;
}

// Version conflict — the narrow caution column at the far left of the review
// table. Measured only against assets already approved: "equal" means one of
// those carries this exact version (typically the same cut in another
// format), "higher" means this delivery is behind one. Two versions arriving
// in the same dump are alternates and never flag each other; quarantined
// assets are not peers either, since a redelivery is the expected fix.
// Computed backend-side — see apply_version_flags in helpers.py.
const CONFLICT_LABELS = {
  equal:  "equal version already approved",
  higher: "higher version already approved",
};

function conflict_formatter(cell) {
  const kind = cell.getValue();
  if (!kind) return "";
  const label = CONFLICT_LABELS[kind] || "version conflict";
  // The peer's filename is the useful part; fall back to its version, then to
  // the bare label, so an older entry with no name recorded still says something.
  const row = cell.getData();
  const peer = row.conflict_name || row.conflict_version || "";
  const title = peer ? label + ": " + peer : label;
  const icon = kind === "higher" ? "version_stale.svg" : "version_conflict.svg";
  return `<img src="/static/icons/${icon}" alt="${escape_html(label)}" title="${escape_html(title)}" class="cell-icon conflict-icon">`;
}

const CONFLICT_COLUMN = {
  title: "!",
  field: "conflict",
  formatter: conflict_formatter,
  headerTooltip: "an equal or higher version of this asset has already been approved",
  hozAlign: "center",
  headerHozAlign: "center",
  width: 52,
  minWidth: 52,
  headerFilter: "list",
  headerFilterParams: {
    values: { higher: "higher exists", equal: "equal exists" },
    clearable: true,
  },
  headerFilterPlaceholder: "all",
};

// QC predicates. Shared by the cell formatters (which colour a single cell) and
// by row_qc_fails (which stamps the row for the "QC fails only" filter), so the
// red text and the filter can never disagree about what counts as a failure.

function codec_fails(codec) {
  return !!(qc_config.codecs.length && codec &&
    !qc_config.codecs.includes(String(codec).toLowerCase()));
}

function fps_fails(framerate) {
  if (framerate === "" || framerate === null || framerate === undefined) return false;
  return !!(qc_config.fps.length &&
    !qc_config.fps.some(allowed => Math.abs(parseFloat(framerate) - allowed) < 0.001));
}

// True when this row fails any QC rule — codec, resolution or framerate.
function row_qc_fails(row) {
  if (codec_fails(row.video_codec)) return true;
  if (fps_fails(row.framerate)) return true;
  const res = qc_resolution_fails(qc_resolution_rules(row.screen), row.width, row.height);
  return res.w || res.h;
}

// Is any QC rule configured at all? With none, every row passes and the toggle
// would be dead weight, so it gets hidden.
function qc_rules_configured() {
  const res = qc_config.resolutions || {};
  return !!(qc_config.codecs.length || qc_config.fps.length ||
    (res.global && res.global.length) ||
    (res.screens && Object.keys(res.screens).length));
}

// Codec — red when QC_CODEC is configured and this codec isn't in the list.
function codec_formatter(cell) {
  const codec = cell.getValue() || "";
  return codec_fails(codec)
    ? qc_span(codec, qc_config.codecs.join(", "))
    : escape_html(codec);
}

// Width / Height — red on whichever dimension matches none of the rules for
// this asset's screen.
function resolution_formatter(dimension) {
  return function(cell) {
    const row = cell.getData();
    const value = cell.getValue();
    const shown = value === null || value === undefined ? "" : value;
    const rules = qc_resolution_rules(row.screen);
    if (!qc_resolution_fails(rules, row.width, row.height)[dimension]) return escape_html(shown);
    const expected = [...new Set(rules.map(r => r[dimension]))].join(" or ");
    return qc_span(shown, expected);
  };
}

// FPS — red when set and matching no allowed value (0.001 tolerance for floats).
function fps_formatter(cell) {
  const value = cell.getValue();
  const framerate = value === null || value === undefined ? "" : value;
  return fps_fails(framerate)
    ? qc_span(framerate, qc_config.fps.join(" or "))
    : escape_html(framerate);
}

// Free-text "contains" filter (case-insensitive).
const TEXT_FILTER = {
  headerFilter: "input",
  headerFilterFunc: "like",
  headerFilterPlaceholder: "filter",
};

// Dropdown built from the values actually present in the scan. valuesLookup
// reads the full data set, not the filtered subset, so narrowing on one column
// never removes options from another column's list.
const LIST_FILTER = {
  headerFilter: "list",
  headerFilterParams: { valuesLookup: true, clearable: true },
  headerFilterPlaceholder: "all",
};

// ── Numeric filters with comparison operators ────────────────────────────────
// Accepts "2992" (exact), "> 3000", ">=3000", "<3000", "<=3000" and "!=1080".
// A bare number matches exactly, within a small tolerance so fractional values
// like 23.976 fps can be typed literally.

const OPERATOR_PATTERN = /^\s*(>=|<=|!=|>|<|=)?\s*(-?\d*\.?\d+)\s*$/;

function operator_match(input, value, scale) {
  const parsed = OPERATOR_PATTERN.exec(String(input));
  if (!parsed) return true;  // mid-typing or nonsense — don't hide anything yet

  const target = parseFloat(parsed[2]);
  if (!isFinite(target)) return true;

  // Reject empties before coercing: Number(null) and Number("") are both 0, so
  // an audio file with no width would otherwise match a "<1000" width filter.
  if (value === null || value === undefined || value === "") return false;
  const number = Number(value) / (scale || 1);
  if (!isFinite(number)) return false;  // non-numeric — filtered out

  switch (parsed[1]) {
    case ">":  return number > target;
    case "<":  return number < target;
    case ">=": return number >= target;
    case "<=": return number <= target;
    case "!=": return Math.abs(number - target) >= 0.001;
    default:   return Math.abs(number - target) < 0.001;  // bare number or "="
  }
}

// field: read the raw numeric twin instead of the displayed value (size_bytes
// for "1.2 GiB", duration_ms for "00:01:30:00"). scale: divide the raw value so
// the user types familiar units (MiB, seconds) rather than bytes or ms.
function operator_filter(field, scale) {
  return function(header_value, row_value, row_data) {
    return operator_match(header_value, field ? row_data[field] : row_value, scale);
  };
}

function number_filter(field, scale, placeholder) {
  return {
    headerFilter: "input",  // not "number": the input must accept > and <
    headerFilterFunc: operator_filter(field, scale),
    headerFilterPlaceholder: placeholder || "= > <",
    minWidth: 80,
  };
}

// ── Right-click to filter ─────────────────────────────────────────────────────
// Right-clicking a cell offers to filter that column by the clicked value. The
// value is written into the column's own header filter, so the filter is
// visible and clearable the normal way rather than being hidden state.

// Columns whose displayed text isn't what their filter expects: Duration shows
// a timecode but filters in seconds, Size shows "1.2 GiB" but filters in MiB.
// [raw field, divisor] — rounded to 3dp, which stays inside operator_match's
// 0.001 tolerance so the clicked row always matches.
const FILTER_VALUE_SOURCE = {
  duration: ["duration_ms", 1000],
  size: ["size_bytes", 1048576],
};

function header_filter_value_for(cell) {
  const source = FILTER_VALUE_SOURCE[cell.getColumn().getField()];
  if (source) {
    const raw = Number(cell.getData()[source[0]]);
    if (!isFinite(raw)) return null;
    return String(Math.round((raw / source[1]) * 1000) / 1000);
  }
  const value = cell.getValue();
  return value === null || value === undefined || value === "" ? null : String(value);
}

// Persisted widths stick, so a layout dragged into a mess would otherwise need
// a manual localStorage purge. Clearing by prefix avoids depending on
// Tabulator's per-key suffixes, and re-applying the definitions rebuilds the
// default layout without a page reload — which would throw away the scan.
function reset_table_layout(table) {
  if (!table) return;
  const options = table.cn4m_options || {};
  const prefix = "tabulator-" + options.persistence_id;
  try {
    Object.keys(window.localStorage)
      .filter(key => key.indexOf(prefix) === 0)
      .forEach(key => window.localStorage.removeItem(key));
  } catch (err) {
    console.warn("could not clear persisted layout", err);  // private mode, etc.
  }
  table.setColumns(asset_columns(options));
}

function cell_context_menu(e, cell) {
  const column = cell.getColumn();
  const filterable = !!column.getDefinition().headerFilter;
  const value = filterable ? header_filter_value_for(cell) : null;
  const items = [];

  // Rename is offered on the review table only — the browse tabs list assets
  // that have already been approved or quarantined, and renaming one of those
  // would diverge from the name recorded in the Google Sheet.
  if (cell.getTable() === asset_table) {
    items.push({
      label: "Rename&hellip;",
      action: () => open_rename_dialog(cell.getRow()),
    });
    items.push({ separator: true });
  }

  if (value !== null) {
    items.push({
      label: `Filter by &ldquo;${escape_html(value)}&rdquo;`,
      action: () => column.setHeaderFilterValue(value),
    });
  }
  if (filterable && column.getHeaderFilterValue()) {
    items.push({
      label: "Clear this column&rsquo;s filter",
      action: () => column.setHeaderFilterValue(""),
    });
  }
  // Scoped to the cell's own table — this menu is shared by all three tables,
  // so reaching for the ingest table here would clear the wrong one.
  const table = cell.getTable();
  items.push({
    label: "Clear all filters",
    action: () => table.clearHeaderFilter(),
  });
  items.push({
    label: "Reset column layout",
    action: () => reset_table_layout(table),
  });
  return items;
}

// Tracked = already pushed to the Google Sheet. Only shown on the browse tabs;
// on the ingest table every row is untracked by definition.
function tracked_formatter(cell) {
  return cell.getValue()
    ? '<span class="tracked-yes" title="pushed to the Google Sheet">&#10003;</span>'
    : '<span class="tracked-no" title="not yet pushed to the Google Sheet">&ndash;</span>';
}

const TRACKED_COLUMN = {
  title: "Tracked",
  field: "tracked",
  formatter: tracked_formatter,
  sorter: "boolean",
  hozAlign: "center",
  headerHozAlign: "center",
  width: 78,
  headerFilter: "list",
  headerFilterParams: { values: { "true": "tracked", "false": "untracked" }, clearable: true },
  headerFilterFunc: (header_value, row_value) => String(!!row_value) === header_value,
  headerFilterPlaceholder: "all",
};

function asset_columns(options) {
  const trailing = (options && options.tracked) ? [TRACKED_COLUMN] : [];
  // Only the ingest table gets the conflict column — the browse tabs list what
  // was already accepted, where the comparison has no one to answer to.
  const leading = (options && options.conflicts) ? [CONFLICT_COLUMN] : [];
  return leading.concat([
    { title: "Folder",        field: "parent",         formatter: folder_formatter,  maxInitialWidth: 260, ...TEXT_FILTER },
    { title: "Name",          field: "name",           formatter: name_formatter,    maxInitialWidth: 340, ...TEXT_FILTER },
    { title: "Screen / Stem", field: "screen",         sorter: screen_sorter,        maxInitialWidth: 180, ...LIST_FILTER },
    { title: "Version",       field: "version",        formatter: version_formatter, sorter: "alphanum",   ...LIST_FILTER },
    { title: "Ext",           field: "extension",      ...LIST_FILTER },
    { title: "Duration",      field: "duration",       sorter: raw_number_sorter("duration_ms"), ...number_filter("duration_ms", 1000, "= > < sec") },
    { title: "Codec",         field: "video_codec",    formatter: codec_formatter,   ...LIST_FILTER },
    { title: "Width",         field: "width",          formatter: resolution_formatter("w"), sorter: "number", ...number_filter() },
    { title: "Height",        field: "height",         formatter: resolution_formatter("h"), sorter: "number", ...number_filter() },
    { title: "FPS",           field: "framerate",      formatter: fps_formatter,             sorter: "number", ...number_filter() },
    { title: "Audio",         field: "audio",          ...LIST_FILTER },
    { title: "Rate",          field: "audio_rate",     sorter: "number", ...number_filter() },
    { title: "Bits",          field: "audio_bits",     sorter: "number", ...number_filter() },
    { title: "Ch",            field: "audio_channels", sorter: "number", ...number_filter() },
    { title: "Size",          field: "size",           sorter: raw_number_sorter("size_bytes"), ...number_filter("size_bytes", 1048576, "= > < MiB"), minWidth: 95 },
  ]).concat(trailing);
}

// Flatten the scan result (keyed by fileid) into Tabulator's row array. Values
// stay raw here — display formatting is the formatters' job.
function asset_rows(assets_by_id) {
  return Object.entries(assets_by_id).map(([fileid, asset]) => {
    const row = {
    fileid: fileid,
    parent: asset.parent || "",
    // display_name excludes screen/version/extension; older entries fall back
    name: asset.display_name || asset.basename || asset.name || "",
    // The actual filename on disk. Not shown in any column — the rename dialog
    // needs something to put in its box, and NAME is the trimmed display form.
    filename: asset.name || "",
    screen: asset.screen || "",
    version: asset.version || "",
    is_version_up: !!asset.is_version_up,
    // Flattened out of the version_conflict object so the column can sort and
    // filter on the kind while the formatter still has the peer to name.
    conflict: (asset.version_conflict && asset.version_conflict.kind) || "",
    conflict_name: (asset.version_conflict && asset.version_conflict.name) || "",
    conflict_version: (asset.version_conflict && asset.version_conflict.version) || "",
    extension: asset.extension || "",
    duration: asset.duration || "",
    duration_ms: asset.duration_ms,
    video_codec: asset.video_codec || "",
    width: asset.width,
    height: asset.height,
    framerate: asset.framerate,
    audio: asset.audio || "",
    audio_rate: asset.audio_rate,
    audio_bits: asset.audio_bits,
    audio_channels: asset.audio_channels,
    size: asset.size || "",
    size_bytes: asset.size_bytes,
    tracked: !!asset.tracked,  // set by /assets/<bucket>; absent (false) on a scan
    };
    row.qc_fail = row_qc_fails(row);  // stamped once here; the toggle filters on it
    return row;
  });
}

// Every table in the app — the ingest review table and the two browse tabs —
// is built here, so columns, QC formatting, filters, clipboard and the
// right-click menu stay identical across them. Options:
//   selectable      checkbox column + row selection (ingest only)
//   tracked         show the TRACKED column (browse tabs only)
//   persistence_id  separate localStorage key per table
//   data            initial rows
//   placeholder     empty-state text
function create_asset_table(element, options) {
  const config = {
    data: options.data || [],
    index: "fileid",              // lets deleteRow() address rows by fileid
    columns: asset_columns(options),
    // fitDataStretch is the only fitData variant whose layout function respects
    // a manually resized column (`e.widthFixed || e.reinitializeWidth()`); the
    // others call reinitializeWidth() unconditionally, which clears the fixed
    // flag and snaps the column back to whatever its longest value needs.
    layout: "fitDataStretch",
    maxHeight: "75vh",            // long lists scroll inside the table (virtual DOM)
    placeholder: options.placeholder || "No assets found.",
    // Column widths/order and the sort survive a reload. Filters deliberately
    // do NOT — see reset_table_layout() and the note in TODO_TABULATOR.md.
    persistence: { columns: true, sort: true },
    persistenceID: options.persistence_id,
    // Ctrl/Cmd-C copies the table out as TSV for Sheets/Excel. "copy" (not true)
    // leaves paste disabled — these are review tables, not editable ones.
    // Row range "active" = the rows passing the current filters, so what you
    // copy is what you see. clipboardCopyStyled:false and formatCells:false send
    // the underlying values rather than our icon/QC markup.
    clipboard: "copy",
    clipboardCopyRowRange: "active",
    clipboardCopyStyled: false,
    clipboardCopyConfig: { columnHeaders: true, formatCells: false, rowGroups: false, columnCalcs: false },
    columnDefaults: {
      headerHozAlign: "left",
      vertAlign: "middle",
      contextMenu: cell_context_menu,  // right-click a value to filter by it
    },
  };

  // Only the ingest table is selectable — the browse tabs are read-only.
  if (options.selectable) {
    config.selectableRows = true;
    config.rowHeader = {
      formatter: "rowSelection",
      titleFormatter: "rowSelection",
      // "active" = rows passing the current filters. Without this the header
      // checkbox selects every row in the table, including filtered-out ones.
      titleFormatterParams: { rowRange: "active" },
      headerSort: false,
      resizable: false,
      frozen: true,
      width: 40,
      hozAlign: "center",
      headerHozAlign: "center",
      cellClick: function(e, cell) { cell.getRow().toggleSelect(); },
    };
  }

  const table = new Tabulator(element, config);
  table.cn4m_options = options;  // reset_table_layout needs these back
  track_empty_state(table);
  return table;
}

// Tabulator stretches its empty-state placeholder to the table's full height,
// so a table with no rows (or a filter that matches none) leaves a tall void
// with one line of text in it and pushes the action buttons below the fold.
// Flag the element and let CSS collapse it — see `.tabulator.is-empty`.
function track_empty_state(table) {
  const mark = function() {
    let empty;
    try {
      empty = table.getDataCount("active") === 0;
    } catch (e) {
      return;  // fires before the row manager is ready — the next event lands
    }
    if (empty === table.element.classList.contains("is-empty")) return;
    table.element.classList.toggle("is-empty", empty);
    // Tabulator measures the table against whatever height CSS allows, so a
    // table that just gained rows would stay stuck at the collapsed height it
    // was measured at. Re-measure once the class change has taken effect.
    if (!empty) setTimeout(() => table.redraw(), 0);
  };
  table.on("tableBuilt", mark);
  table.on("renderComplete", mark);
  table.on("dataProcessed", mark);
  table.on("dataFiltered", mark);
}


// ── Tabs ──────────────────────────────────────────────────────────────────────

// INGEST is the working view; REPO and QUARANTINE are read-only browsers over
// assets.json. Browse data is re-fetched on every activation so approving or
// quarantining on the ingest tab is reflected as soon as you switch across.
function show_tab(name) {
  $('.tab-panel').hide();
  $('#tab-' + name).show();
  $('.obx-tab').removeClass('obx-button-active');
  $('.obx-tab[data-tab="' + name + '"]').addClass('obx-button-active');

  if (name === 'repo' || name === 'quarantine') load_browse_tab(name);
}

// Header line for a browse tab: "12 assets" plus a selection count once rows
// are ticked, so the transcode button's scope is always visible.
function update_browse_status(name) {
  const table = browse_tables[name];
  if (!table) return;
  const total = table.getDataCount();
  const selected = table.getSelectedRows().length;
  const label = total === 1 ? "1 asset" : total + " assets";
  $('#' + name + '_status').text(selected ? label + " \u00b7 " + selected + " selected" : label);
}

function browse_selection_handler(name) {
  const table = browse_tables[name];
  if (!table || table.cn4m_selection_wired) return;
  table.cn4m_selection_wired = true;
  table.on("rowSelectionChanged", () => update_browse_status(name));
}

function load_browse_tab(name) {
  const status = $('#' + name + '_status');
  status.text("Loading\u2026");

  $.getJSON('/assets/' + name)
    .done(function(data) {
      const rows = asset_rows(data);
      const count = rows.length;
      status.text(count === 1 ? "1 asset" : count + " assets");

      browse_selection_handler(name);

      if (browse_tables[name]) {
        // The table was built while its tab was visible, but has been hidden
        // since — redraw(true) re-measures columns against the live width.
        browse_tables[name].replaceData(rows)
          .then(() => browse_tables[name].redraw(true));
        return;
      }

      browse_tables[name] = create_asset_table('#' + name + '-results', {
        data: rows,
        tracked: true,        // these views span both tracked and untracked
        selectable: true,     // rows can be picked for transcoding
        // -v2: bumped when TRACKED moved to the last column. Persisted layouts
        // store column order, so a stale -v1 layout would keep it up front.
        persistence_id: "cn4m-" + name + "-v2",
        placeholder: "No " + BROWSE_LABELS[name] + " assets.",
      });
    })
    .fail(function() {
      status.text("Could not load assets.");
    });
}

// Transcode the rows ticked on a browse tab. The backend resolves each asset
// across all buckets and, for quarantined ones, against the quarantine folder —
// their stored folder still points at where they were originally delivered.
function transcode_browse(name) {
  const table = browse_tables[name];
  if (!table) return;

  const selected = table.getSelectedData().map(row => row.fileid);
  if (!selected.length) {
    alert('Please select at least one asset.');
    return;
  }
  const preset_name = $('#' + name + '-preset-select').val();
  if (!preset_name) {
    alert('Please select a preset.');
    return;
  }

  transcode_progress_destination = '#' + name + '_progress';
  ajax_post_transcode('/transcode_assets', selected, preset_name);
  table.deselectRow();
}


// ── Rename dialog ─────────────────────────────────────────────────────────────
// Right-click a row in the review table -> Rename. The file is renamed in place
// in its own folder by the worker and re-scanned, so the row comes back with
// freshly parsed version/basename fields and re-evaluated version conflicts.
// Reachable from the review table only — see cell_context_menu.

// fileid of the asset the open dialog is renaming; null when it's closed.
let rename_fileid = null;

function wire_rename_dialog() {
  $('#rename-cancel').click(close_rename_dialog);
  $('#rename-confirm').click(submit_rename);
  // Clicking the backdrop closes; clicking the card itself must not.
  $('#rename-modal').click(function(e) { if (e.target === this) close_rename_dialog(); });
  $('#rename-input').keydown(function(e) {
    if (e.key === "Enter") { e.preventDefault(); submit_rename(); }
    if (e.key === "Escape") { e.preventDefault(); close_rename_dialog(); }
  });
}

function open_rename_dialog(row) {
  const data = row.getData();
  rename_fileid = data.fileid;
  $('#rename-folder').text(data.parent ? "in " + data.parent : "");
  $('#rename-error').text("");
  $('#rename-modal').show();
  set_rename_busy(false);

  const input = $('#rename-input').val(data.filename)[0];
  input.focus();
  // Select the stem and leave the extension out of the selection, the way a
  // file manager does — the version number is what's being fixed, not the type.
  const dot = data.filename.lastIndexOf(".");
  input.setSelectionRange(0, dot > 0 ? dot : data.filename.length);
}

function close_rename_dialog() {
  rename_fileid = null;
  $('#rename-modal').hide();
}

// The rename round-trips through the worker, so the dialog stays open — and
// inert — until the task reports back.
function set_rename_busy(busy) {
  $('#rename-confirm').prop('disabled', busy).text(busy ? "RENAMING…" : "RENAME");
  $('#rename-cancel').prop('disabled', busy);
  $('#rename-input').prop('disabled', busy);
}

function rename_dialog_error(message) {
  set_rename_busy(false);
  $('#rename-error').text(message);
}

function submit_rename() {
  if (rename_fileid === null) return;
  const new_name = $('#rename-input').val().trim();
  if (!new_name) {
    rename_dialog_error("Enter a filename.");
    return;
  }
  $('#rename-error').text("");
  set_rename_busy(true);
  $.ajax({
    type: 'POST',
    url: '/rename_asset',
    data: { fileid: rename_fileid, new_name: new_name },
    success: function(data, status, request) {
      poll_rename(request.getResponseHeader('Location'));
    },
    error: function(XMLHttpRequest, textStatus, errorThrown) {
      rename_dialog_error(textStatus + ': ' + errorThrown);
    },
  });
}

// Deliberately not routed through update_progress: that machinery re-polls with
// no delay, and there is no progress worth showing for a single rename anyway.
function poll_rename(status_url) {
  $.getJSON(status_url, function(data) {
    if (data['state'] === 'PENDING' || data['state'] === 'PROGRESS') {
      setTimeout(() => poll_rename(status_url), 200);
      return;
    }
    if (data['state'] === 'FAILURE') {
      rename_dialog_error("Rename failed: " + data['status']);
      return;
    }
    const result = data['result'] || {};
    // A refusal the worker declined on purpose (name taken, file gone, bad
    // characters) — keep the dialog open so the name can be corrected.
    if (result.error) {
      rename_dialog_error(result.error);
      return;
    }
    apply_rename_result(result);
    close_rename_dialog();
    $('#review_asset_progress').html(
      "Renamed <b>" + escape_html(result.old_name) + "</b> to <b>" + escape_html(result.name) + "</b>");
  }).fail(function() {
    rename_dialog_error("Lost contact with the rename task — run the check again to see where it got to.");
  });
}

// Fold a completed rename back into the table: the renamed row is replaced by
// its re-scanned self, and every other visible row is refreshed from the same
// payload, since fixing one version can clear a conflict flag on the row it
// collided with. Rows the current view never had (assets left unreviewed by an
// earlier scan) are deliberately not added — the review table shows the last
// scan, and a rename shouldn't quietly widen that.
function apply_rename_result(result) {
  if (!asset_table) return;
  const by_fileid = {};
  for (const row of asset_rows(result.assets || {})) by_fileid[row.fileid] = row;

  const was_selected = !!(asset_table.getRow(result.old_fileid)
    && asset_table.getRow(result.old_fileid).isSelected());

  const refreshed = asset_table.getData()
    .map(row => by_fileid[row.fileid])
    .filter(row => row !== undefined);

  const sorters = asset_table.getSorters().map(s => ({ column: s.field, dir: s.dir }));

  if (asset_table.getRow(result.old_fileid)) asset_table.deleteRow(result.old_fileid);
  Promise.resolve(refreshed.length ? asset_table.updateData(refreshed) : null)
    .then(() => by_fileid[result.fileid] ? asset_table.addData([by_fileid[result.fileid]]) : null)
    .then(() => {
      // addData appends, so re-apply the sort to drop the new row into place.
      if (sorters.length) asset_table.setSort(sorters);
      if (was_selected) asset_table.selectRow([result.fileid]);
      update_qc_button();
      update_selection_count();
      update_flagged_select_button();
    });
}


// ── Progressive disclosure of the ingest panes ────────────────────────────────
// The review pane opens once a scan has produced a table; the track pane opens
// once something has been approved or quarantined.

function reveal_review_pane() {
  $('#pane-review').show();
}

function reveal_track_pane() {
  $('#pane-track').show();
}

// Approving in an earlier session would otherwise leave the track pane
// unreachable, so open it on load if anything is still waiting to be pushed.
function reveal_track_pane_if_pending() {
  $.getJSON('/untracked_count', function(data) {
    const count = (data && data.count) || 0;
    if (count > 0) reveal_track_pane();
    // Seed the suite rail with something the per-pane progress lines don't say:
    // what is still sitting between approval and the Google Sheet.
    set_app_status(count
      ? count + (count === 1 ? " asset" : " assets") + " waiting to be tracked"
      : "Ready");
  }).fail(function() {
    set_app_status("Could not reach the cn4m server", "error");
  });
}


// ── Ingest review table ───────────────────────────────────────────────────────

// Build it on the first scan; refresh its data on every scan after that, which
// keeps the user's column widths and filters.
function render_asset_table(assets_by_id) {
  const rows = asset_rows(assets_by_id);

  if (asset_table) {
    asset_table.replaceData(rows).then(update_qc_button);
    return;
  }

  asset_table = create_asset_table("#results", {
    data: rows,
    selectable: true,
    conflicts: true,     // caution column for equal/higher versions already held
    persistence_id: PERSISTENCE_ID,
    placeholder: "No new assets found.",
  });

  // Selection survives a filter change, so a row can be selected while hidden.
  // Show the count next to the action buttons to keep that honest.
  asset_table.on("tableBuilt", update_qc_button);
  asset_table.on("rowSelectionChanged", () => {
    update_selection_count();
    update_flagged_select_button();
  });
  // dataFiltered is dispatched from *inside* Tabulator's filter routine, before
  // the filtered set is assigned to activeRows — so getRows("active") is one
  // filter-change stale in here. The event's second argument is the fresh set.
  asset_table.on("dataFiltered", (filters, rows) => {
    update_selection_count(rows);
    update_flagged_select_button();
  });
}

// ── Flagged assets: filter + select ───────────────────────────────────────────
// "Flagged" = fails any QC rule (codec, resolution or framerate), i.e. the rows
// showing red cells.

function toggle_qc_filter() {
  if (!asset_table) return;
  set_qc_filter(!qc_filter_active);
}

function set_qc_filter(active) {
  qc_filter_active = active;
  if (active) {
    asset_table.addFilter("qc_fail", "=", true);
  } else {
    asset_table.removeFilter("qc_fail", "=", true);
  }
  $('#toggle-qc').toggleClass('obx-button-active', active);
}

// Flagged rows currently passing the filters. Scoped to "active" to match the
// header select-all, so we never touch a row the user can't see.
function flagged_rows_in_view() {
  if (!asset_table) return [];
  return asset_table.getRows("active").filter(row => row.getData().qc_fail);
}

// True when every visible flagged row is already selected — this drives the
// toggle's direction, so manually unticking one flags the button back to
// "select" rather than leaving it out of step with the table.
function all_flagged_selected() {
  const flagged = flagged_rows_in_view();
  if (!flagged.length) return false;
  const selected = new Set(asset_table.getSelectedRows());
  return flagged.every(row => selected.has(row));
}

function select_all_flagged() {
  if (!asset_table) return;
  const flagged = flagged_rows_in_view();
  if (!flagged.length) return;
  if (all_flagged_selected()) {
    asset_table.deselectRow(flagged);
  } else {
    asset_table.selectRow(flagged);
  }
}

// Matches SHOW FLAGGED ONLY: the label stays put and the orange highlight
// carries the state, so both toggles read the same way.
function update_flagged_select_button() {
  $('#select-flagged').toggleClass('obx-button-active', all_flagged_selected());
}

// The filter button's label carries the count, so a finished scan reports its QC
// state at a glance without anyone having to click. Both buttons hide entirely
// when no QC rules are configured, and disable when the scan is clean.
function update_qc_button() {
  const filter_button = $('#toggle-qc');
  const select_button = $('#select-flagged');
  if (!asset_table) return;

  if (!qc_rules_configured()) {
    filter_button.hide();
    select_button.hide();
    return;
  }

  const failing = asset_table.getData().filter(row => row.qc_fail).length;
  filter_button.show();
  select_button.show();

  if (!failing) {
    if (qc_filter_active) set_qc_filter(false);  // don't leave an empty table behind
    filter_button.text("NO FLAGGED ASSETS").prop("disabled", true);
    select_button.prop("disabled", true);
    return;
  }

  filter_button.text(`SHOW FLAGGED ONLY (${failing})`).prop("disabled", false);
  select_button.prop("disabled", false);
  update_flagged_select_button();
}


// "12 selected" / "12 selected (3 hidden by filter)" / "" when nothing is picked.
// active_rows may be supplied by a caller that has a fresher set than the table.
function update_selection_count(active_rows) {
  if (!asset_table) return;
  const selected = asset_table.getSelectedRows();
  if (!selected.length) {
    $('#selection_count').text("");
    return;
  }
  const visible = new Set(active_rows || asset_table.getRows("active"));
  const hidden = selected.filter(row => !visible.has(row)).length;
  $('#selection_count').text(
    hidden ? `${selected.length} selected (${hidden} hidden by filter)`
           : `${selected.length} selected`
  );
}


// ── check_assets progress + table rendering ───────────────────────────────────
// Polls the task status endpoint and, once complete, builds the sortable asset table.

function handle_check_assets_progress(status_task, status_url) {
  $.getJSON(status_url, function(data) {
    console.log(data)
    percent = parseInt(data['current'] * 100 / data['total']);

    if (data['state'] == 'PENDING') {
        message = "Starting Asset Check"
        update_progress(status_task, status_url);

    } else if (data['state'] == 'PROGRESS') {
        if (data['total'] == 0) {
            message = null
        } else {
            message = percent + "% Complete - Checking Asset " + data['status']
        }
        update_progress(status_task, status_url);

    } else if (data['status'] == 'COMPLETE') {
        message = "Asset Check Complete"

        // Sort by dumbpath (case-insensitive parent.filename), stash the scan, render
        const data_sorted = Object.fromEntries(
            Object.entries(data['result']['assets']).sort((a, b) =>
                (a[1]?.dumbpath || "").localeCompare(b[1]?.dumbpath || "")
            )
        );
        data['result']['assets'] = data_sorted;
        render_asset_table(data_sorted);
        reveal_review_pane();

        // ── Flag display ───────────────────────────────────────────────────────
        // Show any flagged (invalid/missing) files below the table, then clear them
        // so they only appear once (on the scan that found them).
        flags = ""
        for (const [key, value] of Object.entries(data['result']['flags'])) {
          obj = data['result']['flags'][key];
          flags += '<span class="severity-' + obj['severity'] + '">'
          flags += obj['note']
          flags += ": <b>"
          flags += obj['name']
          flags += "</b></span><br>"
        }
        $('#review_asset_flags').html(flags);
        ajax_post_simple('/clear_flags')  // archive flags so they don't show again on the next scan

    } else if (data['state'] != 'PENDING' && data['state'] != 'PROGRESS') {
        if ('result' in data) {
            message = 'Result: ' + data['result']
        } else {
            message = 'Result: ' + data['state']
        }
    } else {
        update_progress(status_task, status_url);
        message = null
    }

    $('#check_asset_progress').html(message);
  });
}


// Map a file extension to its file-type icon filename, or null if unknown.
// Extensions are matched case-insensitively.
function get_file_type_icon(ext) {
  const lower = normalize_ext(ext);
  if (!lower) return null;
  if (AUDIO_EXTS.includes(lower)) return "audio_file.svg";
  if (IMAGE_EXTS.includes(lower)) return "image_file.svg";
  if (VIDEO_EXTS.includes(lower)) return "video_file.svg";
  return null;
}


// ── Helpers ───────────────────────────────────────────────────────────────────

// Generic progress poller used by all tasks except check_assets
function get_update_progress_feedback(status_task, status_url, msg_destination, msg_pending, msg_progress, msg_complete) {
  $.getJSON(status_url, function(data) {
          percent = parseInt(data['current'] * 100 / data['total']);
          if (data['state'] == 'PENDING') {
              message = msg_pending
              update_progress(status_task, status_url);
          } else if (data['state'] == 'PROGRESS') {
              if (data['total'] == 0) {
                  message = null
              } else {
                  message = percent + "% Complete - " + msg_progress + " " + data['status']
              }
              update_progress(status_task, status_url);
          } else if (data['status'] == 'COMPLETE') {
              message = msg_complete
          } else if (data['state'] != 'PENDING' && data['state'] != 'PROGRESS') {
              if ('result' in data) {
                  message = 'Result: ' + data['result']
              } else {
                  message = 'Result: ' + data['state']
              }
          } else {
              update_progress(status_task, status_url);
              message = null
          }
          $(msg_destination).html(message);
      })
}

// Return an array of fileid values for all checked rows
function get_selected_assets() {
  if (!asset_table) return [];
  return asset_table.getSelectedData().map(row => row.fileid);
}

// Remove rows from the table by fileid after approve/quarantine
function remove_assets_from_table(assets) {
  for (const asset of assets) {
    if (asset_table && asset_table.getRow(asset)) asset_table.deleteRow(asset);
  }
}

// POST to a URL with no payload; used for check_assets, track_assets, clear_flags
function ajax_post_simple(url) {
  $.ajax({
    type: 'POST',
    url: url,
    success: function(data, status, request) {
      status_url = request.getResponseHeader('Location');
      update_progress(url, status_url);
    },
    error: function(XMLHttpRequest, textStatus, errorThrown) {
      alert(textStatus + ': ' + errorThrown);
    }
  });
}

// POST to a URL with a JSON array of selected fileids; used for approve/quarantine
function ajax_post_with_selection(url, selected_assets) {
  $.ajax({
    type: 'POST',
    url: url,
    data: {
        javascript_data: JSON.stringify(selected_assets)
    },
    success: function(data, status, request) {
        status_url = request.getResponseHeader('Location');
        update_progress(url, status_url);
    },
    error: function(XMLHttpRequest, textStatus, errorThrown) {
        alert(textStatus + ': ' + errorThrown);
    }
  });
}

// POST selected assets + chosen preset name; used for transcode
function ajax_post_transcode(url, selected_assets, preset_name) {
  $.ajax({
    type: 'POST',
    url: url,
    data: {
        javascript_data: JSON.stringify(selected_assets),
        preset_name: preset_name
    },
    success: function(data, status, request) {
        status_url = request.getResponseHeader('Location');
        update_progress(url, status_url);
    },
    error: function(XMLHttpRequest, textStatus, errorThrown) {
        alert(textStatus + ': ' + errorThrown);
    }
  });
}
