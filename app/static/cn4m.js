// cn4m.js
// Frontend logic for the cn4m asset conformance tool.
// Handles AJAX calls to the Flask backend, Celery task progress polling,
// dynamic table rendering, column sorting, and checkbox selection.


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
  $('input[name="review_checkbox"]').prop('checked', false);
  document.querySelector('th input[type="checkbox"]').checked = false;
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
  $('input[name="review_checkbox"]').prop('checked', false);
  document.querySelector('th input[type="checkbox"]').checked = false;
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
    case "extract_audio":
      msg_destination = "#review_asset_progress"
      msg_pending = "Attempting to Extract Audio"
      msg_progress = "Attempting to Extract Audio in Progress"
      msg_complete = "Attempt to Extract Audio Complete - <a href=\"#\" onclick=\"check_assets()\">Click to Re-Check Assets</a>"
      get_update_progress_feedback(status_task, status_url, msg_destination, msg_pending, msg_progress, msg_complete)
      break;

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

        // ── Build sortable results table ───────────────────────────────────────
        let asset_table = `
            <div class="table-responsive">
                <table id="sortableTable" class="table table-dark table-striped table-hover table-sm fs-8 fw-lighter">
                    <thead>
                        <tr>
                            <th class="pr-4 py-1"><input type="checkbox" onClick="toggle_checkboxes(this)" /></th>
                            <th class="pr-4" data-type="string">Folder</th>
                            <th class="pr-4" data-type="string">Name</th>
                            <th class="pr-4" data-type="string">Screen / Stem</th>
                            <th class="pr-4" data-type="string">Version</th>
                            <th class="pr-4" data-type="string">Ext</th>
                            <th class="pr-4" data-type="number">Duration</th>
                            <th class="pr-4" data-type="string">Codec</th>
                            <th class="pr-4" data-type="number">Width</th>
                            <th class="pr-4" data-type="number">Height</th>
                            <th class="pr-4" data-type="number">FPS</th>
                            <th class="pr-4" data-type="string">Audio</th>
                            <th class="pr-4" data-type="number">Rate</th>
                            <th class="pr-4" data-type="number">Bits</th>
                            <th class="pr-4" data-type="number">Ch</th>
                            <th class="pr-4" data-type="string">Size</th>
                        </tr>
                    </thead>
                    <tbody>`;

        // Sort results by dumbpath (case-insensitive parent.filename) before rendering
        const data_sorted = Object.fromEntries(
            Object.entries(data['result']['assets']).sort((a, b) =>
                (a[1]?.dumbpath || "").localeCompare(b[1]?.dumbpath || "")
            )
        );
        data['result']['assets'] = data_sorted;

        // Build one table row per asset
        for (const [key, value] of Object.entries(data['result']['assets'])) {
            obj = data['result']['assets'][key];
            fileid = key;
            name = obj['basename'] || obj['name'] || "";  // basename excludes version + extension; falls back to full name
            version = obj['version'] || "";
            extension = obj['extension'] || "";
            // Prepend an icon next to the version:
            //   green up-arrow (version_up.svg) if basename matches an existing tracked/untracked asset
            //   orange plus   (new_file.svg)   otherwise — treated as a brand-new asset
            const version_icon = obj['is_version_up']
                ? `<img src="/static/icons/version_up.svg" alt="version up" title="version up — basename matches an existing tracked/untracked asset" style="height: 1em; vertical-align: middle;">`
                : `<img src="/static/icons/new_file.svg" alt="new file" title="new file — no matching basename in existing assets" style="height: 1em; vertical-align: middle;">`;
            const version_cell = `${version_icon} ${version}`;

            // Prepend a file-type icon (audio / image / video) to the name, if we recognize the extension
            const ext_icon_file = get_file_type_icon(extension);
            const name_cell = ext_icon_file
                ? `<img src="/static/icons/${ext_icon_file}" alt="${extension}" title="${extension}" style="height: 1em; vertical-align: middle;"> ${name}`
                : name;
            parent = (obj['parent'] || "").replace(/ /g, '&nbsp;');  // preserve folder name spaces in HTML
            screen = obj['screen'] || "";
            duration = obj['duration'] || "";
            video_codec = obj['video_codec'] || "";
            width = obj['width'] || "";
            height = obj['height'] || "";
            framerate = obj['framerate'] || "";
            audio = obj['audio'] || "";
            audio_rate = obj['audio_rate'] || "";
            audio_bits = obj['audio_bits'] || "";
            audio_channels = obj['audio_channels'] || "";
            size = obj['size'] || "";

            // Row id = fileid (no # prefix) so remove_assets_from_table can find it by getElementById
            asset_table += `
                <tr id="${fileid}" class="even:bg-zinc-800 odd:bg-zinc-900 text-slate-300 hover:bg-zinc-700">
                    <td class="pr-4 py-1"><input class="obx-checkbox" name="review_checkbox" type="checkbox" value="${fileid}"></td>
                    <td class="pr-4">${parent}</td>
                    <td class="pr-4">${name_cell}</td>
                    <td class="pr-4">${screen}</td>
                    <td class="pr-4">${version_cell}</td>
                    <td class="pr-4">${extension}</td>
                    <td class="pr-4">${duration}</td>
                    <td class="pr-4">${video_codec}</td>
                    <td class="pr-4">${width}</td>
                    <td class="pr-4">${height}</td>
                    <td class="pr-4">${framerate}</td>
                    <td class="pr-4">${audio}</td>
                    <td class="pr-4">${audio_rate}</td>
                    <td class="pr-4">${audio_bits}</td>
                    <td class="pr-4">${audio_channels}</td>
                    <td class="pr-4">${size}</td>
                </tr>`;
        }

        asset_table += `
            </tbody>
            </table>
        </div>`;

        // Insert the table into the DOM, then attach sort listeners
        $('#results').html(asset_table);
        makeTableSortable();
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


// ── Table sorting ─────────────────────────────────────────────────────────────
// Makes all header cells (except the checkbox column) clickable to sort the table.
// Toggles between ascending and descending on repeated clicks.
// Columns marked data-type="number" sort numerically; others sort alphabetically.

function makeTableSortable() {
    const table = document.getElementById("sortableTable");
    if (!table) return;

    const headers = table.querySelectorAll("thead th");
    const tbody = table.querySelector("tbody");
    let sortOrder = {};  // tracks current sort direction per column index

    headers.forEach((header, colIndex) => {
        if (colIndex === 0) return;  // skip the checkbox column

        header.style.cursor = "pointer";

        header.addEventListener("click", () => {
            const dataType = header.getAttribute("data-type") || "string";
            const isScreenCol = header.textContent.trim() === "Screen / Stem";
            const extColIndex = isScreenCol ? Array.from(headers).findIndex(h => h.textContent.trim() === "Ext") : -1;
            let rowsArray = Array.from(tbody.querySelectorAll("tr"));

            const audioExts = ["wav", "aiff", "aif", "mp3", "flac", "ogg", "m4a", "aac", "wma"];

            rowsArray.sort((rowA, rowB) => {
                let cellA = rowA.children[colIndex]?.innerText.trim() || "";
                let cellB = rowB.children[colIndex]?.innerText.trim() || "";

                let comparison = 0;

                if (isScreenCol && extColIndex >= 0) {
                    const extA = (rowA.children[extColIndex]?.innerText.trim() || "").toLowerCase().replace(/^\./, '');
                    const extB = (rowB.children[extColIndex]?.innerText.trim() || "").toLowerCase().replace(/^\./, '');
                    const isAudioA = audioExts.includes(extA);
                    const isAudioB = audioExts.includes(extB);
                    if (isAudioA !== isAudioB) {
                        comparison = isAudioA ? -1 : 1;
                    } else {
                        comparison = cellA.localeCompare(cellB);
                    }
                } else if (dataType === "number") {
                    comparison = (parseFloat(cellA) || 0) - (parseFloat(cellB) || 0);
                } else {
                    comparison = cellA.localeCompare(cellB);
                }

                return sortOrder[colIndex] === "asc" ? comparison : -comparison;
            });

            // Toggle direction for next click
            sortOrder[colIndex] = sortOrder[colIndex] === "asc" ? "desc" : "asc";

            // Re-render sorted rows
            tbody.innerHTML = "";
            rowsArray.forEach(row => tbody.appendChild(row));
        });
    });
}


// Map a file extension to its file-type icon filename, or null if unknown.
// Extensions are matched case-insensitively.
function get_file_type_icon(ext) {
  if (!ext) return null;
  const lower = String(ext).toLowerCase().replace(/^\./, '');
  const audio = ["wav", "aiff", "aif", "mp3", "flac", "ogg", "m4a", "aac", "wma"];
  const image = ["png", "jpeg", "jpg", "tiff", "tif", "tga", "exr", "bmp", "gif", "webp", "dpx", "heic"];
  const video = ["mov", "mkv", "mp4", "avi", "webm", "m4v", "wmv", "flv", "mpg", "mpeg"];
  if (audio.includes(lower)) return "audio_file.svg";
  if (image.includes(lower)) return "image_file.svg";
  if (video.includes(lower)) return "video_file.svg";
  return null;
}


// ── Helpers ───────────────────────────────────────────────────────────────────

function select_all_audio() {
  var audioExts = ["wav", "aiff", "aif", "mp3", "flac", "ogg", "m4a", "aac", "wma"];
  var table = document.getElementById("sortableTable");
  if (!table) return;
  var headers = table.querySelectorAll("thead th");
  var extColIndex = Array.from(headers).findIndex(h => h.textContent.trim() === "Ext");
  if (extColIndex < 0) return;

  var rows = table.querySelectorAll("tbody tr");
  for (var i = 0; i < rows.length; i++) {
    var ext = (rows[i].children[extColIndex]?.innerText.trim() || "").toLowerCase().replace(/^\./, '');
    var checkbox = rows[i].querySelector("input[name='review_checkbox']");
    if (checkbox && audioExts.includes(ext)) {
      checkbox.checked = true;
    }
  }
  document.querySelector('th input[type="checkbox"]').checked = false;
}

// Toggle all review checkboxes on/off using the header checkbox
function toggle_checkboxes(source) {
  checkboxes = document.getElementsByName('review_checkbox');
  for(var i=0, n=checkboxes.length;i<n;i++) {
    checkboxes[i].checked = source.checked;
  }
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
  selected_assets = []
  $("input[name='review_checkbox']:checkbox:checked").each(function (index, obj) {
    selected_assets.push($(this).val());
  });
  return selected_assets
}

// Remove rows from the table by fileid after approve/quarantine
function remove_assets_from_table(assets) {
    for (const asset of assets) {
      var row = document.getElementById(asset);
      if (row) row.parentNode.removeChild(row);
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
