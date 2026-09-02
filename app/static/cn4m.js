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

// ── Button handlers ───────────────────────────────────────────────────────────
// These are wired up to the buttons in index.html via $(function() { ... }) at
// the bottom of that file.

function check_assets() {
  ajax_post_simple('/check_assets')
}

function approve_assets() {
  selected_assets = get_selected_assets()
  ajax_post_with_selection('/approve_assets', selected_assets)
  remove_assets_from_table(selected_assets)  // optimistically remove rows while the task runs
}

function quarantine_assets() {
  selected_assets = get_selected_assets()
  ajax_post_with_selection('/quarantine_assets', selected_assets)
  remove_assets_from_table(selected_assets)  // optimistically remove rows while the task runs
}

function track_assets() {
  ajax_post_simple('/track_assets')
}


// ── Preset loader ─────────────────────────────────────────────────────────────
// Fetches the available ffmpeg presets from the backend and populates the dropdown.

function load_ffmpeg_presets() {
  $.getJSON('/ffmpeg_presets', function(presets) {
    var $select = $('#ffmpeg-preset-select');
    $select.find('option:not(:first)').remove();
    $.each(presets, function(i, preset) {
      $select.append($('<option>', { value: preset.name, text: preset.label }));
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
  ajax_post_transcode('/quarantine_and_transcode', selected, preset_name);
  if (asset_table) asset_table.deselectRow();
  remove_assets_from_table(selected);
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
      msg_destination = "#review_asset_progress"
      msg_pending = "Starting Transcode"
      msg_progress = "Transcoding"
      msg_complete = "Transcode Complete - <a href=\"#\" onclick=\"check_assets()\">Click to Re-Check Assets</a>"
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

function asset_columns() {
  return [
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
  ];
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
    screen: asset.screen || "",
    version: asset.version || "",
    is_version_up: !!asset.is_version_up,
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
    };
    row.qc_fail = row_qc_fails(row);  // stamped once here; the toggle filters on it
    return row;
  });
}

// Build the table on the first scan; refresh its data on every scan after that
// (which keeps the user's column widths and, later, their filters).
function render_asset_table(assets_by_id) {
  const rows = asset_rows(assets_by_id);

  if (asset_table) {
    asset_table.replaceData(rows).then(update_qc_button);
    return;
  }

  asset_table = new Tabulator("#results", {
    data: rows,
    index: "fileid",              // lets deleteRow() address rows by fileid
    columns: asset_columns(),
    // fitDataStretch is the only fitData variant whose layout function respects
    // a manually resized column (`e.widthFixed || e.reinitializeWidth()`); the
    // others call reinitializeWidth() unconditionally, which clears the fixed
    // flag and snaps the column back to whatever its longest value needs.
    layout: "fitDataStretch",
    maxHeight: "75vh",            // long scans scroll inside the table (virtual DOM)
    placeholder: "No new assets found.",
    selectableRows: true,
    columnDefaults: { headerHozAlign: "left", vertAlign: "middle" },
    rowHeader: {
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
    },
  });

  // Selection survives a filter change, so a row can be selected while hidden.
  // Show the count next to the action buttons to keep that honest.
  asset_table.on("tableBuilt", update_qc_button);
  asset_table.on("rowSelectionChanged", () => update_selection_count());
  // dataFiltered is dispatched from *inside* Tabulator's filter routine, before
  // the filtered set is assigned to activeRows — so getRows("active") is one
  // filter-change stale in here. The event's second argument is the fresh set.
  asset_table.on("dataFiltered", (filters, rows) => update_selection_count(rows));
}

// ── QC fails filter ───────────────────────────────────────────────────────────

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

// Label carries the failure count, so a finished scan reports its QC state at a
// glance without anyone having to click. Hidden entirely when no QC rules are
// configured, disabled when the scan is clean.
function update_qc_button() {
  const button = $('#toggle-qc');
  if (!asset_table) return;

  if (!qc_rules_configured()) {
    button.hide();
    return;
  }

  const failing = asset_table.getData().filter(row => row.qc_fail).length;
  button.show();

  if (!failing) {
    if (qc_filter_active) set_qc_filter(false);  // don't leave an empty table behind
    button.text("NO QC FAILS").prop("disabled", true);
    return;
  }

  button.text(`QC FAILS ONLY (${failing})`).prop("disabled", false);
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
        $('#review-actions').show();
        $('.review-buttons').show();

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

// Check or uncheck every audio row, deciding audio-ness from the scan data
// rather than from the rendered Ext column.
function set_audio_selection(checked) {
  if (!asset_table) return;
  // "active" = rows currently passing any filters, so this stays correct in Phase 6
  const audio_rows = asset_table.getRows("active")
    .filter(row => is_audio_ext(row.getData().extension));
  if (checked) {
    asset_table.selectRow(audio_rows);
  } else {
    asset_table.deselectRow(audio_rows);
  }
}

function select_all_audio() {
  set_audio_selection(true);
}

function deselect_all_audio() {
  set_audio_selection(false);
}

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
