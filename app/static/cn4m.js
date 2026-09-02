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

// Codec — red when QC_CODEC is configured and this codec isn't in the list.
function codec_formatter(cell) {
  const codec = cell.getValue() || "";
  const fail = qc_config.codecs.length && codec &&
    !qc_config.codecs.includes(String(codec).toLowerCase());
  return fail ? qc_span(codec, qc_config.codecs.join(", ")) : escape_html(codec);
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
  const fail = qc_config.fps.length && framerate !== "" &&
    !qc_config.fps.some(allowed => Math.abs(parseFloat(framerate) - allowed) < 0.001);
  return fail ? qc_span(framerate, qc_config.fps.join(" or ")) : escape_html(framerate);
}

function asset_columns() {
  return [
    { title: "Folder",        field: "parent",         formatter: folder_formatter, maxInitialWidth: 260 },
    { title: "Name",          field: "name",           formatter: name_formatter,   maxInitialWidth: 340 },
    { title: "Screen / Stem", field: "screen",         sorter: screen_sorter,       maxInitialWidth: 180 },
    { title: "Version",       field: "version",        formatter: version_formatter, sorter: "alphanum" },
    { title: "Ext",           field: "extension" },
    { title: "Duration",      field: "duration",       sorter: raw_number_sorter("duration_ms") },
    { title: "Codec",         field: "video_codec",    formatter: codec_formatter },
    { title: "Width",         field: "width",          formatter: resolution_formatter("w"), sorter: "number" },
    { title: "Height",        field: "height",         formatter: resolution_formatter("h"), sorter: "number" },
    { title: "FPS",           field: "framerate",      formatter: fps_formatter,             sorter: "number" },
    { title: "Audio",         field: "audio" },
    { title: "Rate",          field: "audio_rate",     sorter: "number" },
    { title: "Bits",          field: "audio_bits",     sorter: "number" },
    { title: "Ch",            field: "audio_channels", sorter: "number" },
    { title: "Size",          field: "size",           sorter: raw_number_sorter("size_bytes"), minWidth: 90 },
  ];
}

// Flatten the scan result (keyed by fileid) into Tabulator's row array. Values
// stay raw here — display formatting is the formatters' job.
function asset_rows(assets_by_id) {
  return Object.entries(assets_by_id).map(([fileid, asset]) => ({
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
  }));
}

// Build the table on the first scan; refresh its data on every scan after that
// (which keeps the user's column widths and, later, their filters).
function render_asset_table(assets_by_id) {
  const rows = asset_rows(assets_by_id);

  if (asset_table) {
    asset_table.replaceData(rows);
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
      headerSort: false,
      resizable: false,
      frozen: true,
      width: 40,
      hozAlign: "center",
      headerHozAlign: "center",
      cellClick: function(e, cell) { cell.getRow().toggleSelect(); },
    },
  });
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
