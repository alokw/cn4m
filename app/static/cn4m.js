function check_assets() {
  ajax_post_simple('/check_assets')
}

function approve_assets() {
  selected_assets = get_selected_assets()
  ajax_post_with_selection('/approve_assets', selected_assets)
  remove_assets_from_table(selected_assets)
}

function quarantine_assets() {
  selected_assets = get_selected_assets()
  ajax_post_with_selection('/quarantine_assets', selected_assets)
  remove_assets_from_table(selected_assets)
}

function track_assets() {
  ajax_post_simple('/track_assets')
}


function extractAudio(id){
  ajax_post_simple('/extract_audio/' + fileid)
}

function update_progress(status_task, status_url) {

  switch(status_task) {
    case "/approve_assets":
      msg_destination = "#review_asset_progress"
      msg_pending = "Starting Approval"
      msg_progress = "Approving Assets"
      msg_complete = "Approval Complete"
      get_update_progress_feedback(status_task, status_url, msg_destination, msg_pending, msg_progress, msg_complete)
      break;

    case "/quarantine_assets":
      msg_destination = "#review_asset_progress"
      msg_pending = "Starting Quarantine"
      msg_progress = "Quarantining Assets"
      msg_complete = "Quarantine Complete"
      get_update_progress_feedback(status_task, status_url, msg_destination, msg_pending, msg_progress, msg_complete)
      break;

    case "/track_assets":
      msg_destination = "#track_assets_progress"
      msg_pending = "Connecting to Google Sheet"
      msg_progress = "Tracking Assets"
      msg_complete = "Assets Pushed to Tracker"
      get_update_progress_feedback(status_task, status_url, msg_destination, msg_pending, msg_progress, msg_complete)
      break;

    case "/check_assets":
      // send GET request to status URL
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
        }   else if (data['status'] == 'COMPLETE') {
            message = "Asset Check Complete"





            // Generate the table with clickable headers
            let asset_table = `
                <div class="table-responsive">
                    <table id="sortableTable" class="table table-dark table-striped table-hover table-sm fs-8 fw-lighter">
                        <thead>
                            <tr>
                                <th class="pr-4 py-1"><input type="checkbox" onClick="toggle_checkboxes(this)" /></th>
                                <th class="pr-4" data-type="string">Folder</th>
                                <th class="pr-4" data-type="string">Name</th>
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
                                <th class="pr-4" data-type="string">Actions</th>
                            </tr>
                        </thead>
                        <tbody>`;

            // Sort results ensuring "dumbpath" exists
            const data_sorted = Object.fromEntries(
                Object.entries(data['result']['assets']).sort((a, b) => 
                    (a[1]?.dumbpath || "").localeCompare(b[1]?.dumbpath || "")
                )
            );
            data['result']['assets'] = data_sorted;

            // Populate table rows
            for (const [key, value] of Object.entries(data['result']['assets'])) {
                obj = data['result']['assets'][key];
                fileid = key;
                name = obj['name'] || "";
                parent = (obj['parent'] || "").replace(/ /g, '&nbsp;');
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

                asset_table += `
                    <tr id=#` + fileid + ` class="even:bg-zinc-800 odd:bg-zinc-900 text-slate-300 hover:bg-zinc-700">
                        <td class="pr-4 py-1"><input class="obx-checkbox" name="review_checkbox" type="checkbox" value="${fileid}"></td>
                        <td class="pr-4">${parent}</td>
                        <td class="pr-4">${name}</td>
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
                        <td class="pr-4"><button class="obx-actionbutton" title="Extract Audio to WAV" value="${fileid}" onclick="extractAudio(this.value)">&#9836</button></td>
                    </tr>`;
            }

            asset_table += `
                </tbody>
                </table>
            </div>`;

            // Insert the table into the DOM first
            $('#results').html(asset_table);


            // **Now Attach Click Event Listeners After Table is in the DOM**
            function makeTableSortable() {
                const table = document.getElementById("sortableTable");
                if (!table) return;

                const headers = table.querySelectorAll("thead th");
                const tbody = table.querySelector("tbody");
                
                let sortOrder = {}; // Track column sort order

                headers.forEach((header, colIndex) => {
                    if (colIndex === 0) return; // Skip checkbox header

                    header.style.cursor = "pointer"; // Indicate clickable headers

                    header.addEventListener("click", () => {
                        const dataType = header.getAttribute("data-type") || "string";

                        // Convert table rows to an array
                        let rowsArray = Array.from(tbody.querySelectorAll("tr"));

                        // Sort based on column content
                        rowsArray.sort((rowA, rowB) => {
                            let cellA = rowA.children[colIndex]?.innerText.trim() || "";
                            let cellB = rowB.children[colIndex]?.innerText.trim() || "";

                            let comparison = 0;
                            if (dataType === "number") {
                                comparison = (parseFloat(cellA) || 0) - (parseFloat(cellB) || 0);
                            } else {
                                comparison = cellA.localeCompare(cellB);
                            }

                            return sortOrder[colIndex] === "asc" ? comparison : -comparison;
                        });

                        // Toggle sort order for next click
                        sortOrder[colIndex] = sortOrder[colIndex] === "asc" ? "desc" : "asc";

                        // Re-insert sorted rows
                        tbody.innerHTML = "";
                        rowsArray.forEach(row => tbody.appendChild(row));
                    });
                });
            }

            // **Run the function after the table has been inserted**
            makeTableSortable();


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
            ajax_post_simple('/clear_flags')


        }   else if (data['state'] != 'PENDING' && data['state'] != 'PROGRESS') {
            if ('result' in data) {
                message = 'Result: ' + data['result']
            }   else {
                // something unexpected happened
                message = 'Result: ' + data['state']
            }
        } else {
          // re-check
          update_progress(status_task, status_url);
          message = null
        }


        $('#check_asset_progress').html(message);

      });
  }
}


// -------------------- CN4M HELPERS --------------------

function toggle_checkboxes(source) {
  checkboxes = document.getElementsByName('review_checkbox');
  for(var i=0, n=checkboxes.length;i<n;i++) {
    checkboxes[i].checked = source.checked;
  }
}

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
          }   else if (data['status'] == 'COMPLETE') {
              message = msg_complete
          }   else if (data['state'] != 'PENDING' && data['state'] != 'PROGRESS') {
              if ('result' in data) {
                  message = 'Result: ' + data['result']
              }   else {
                  message = 'Result: ' + data['state']
              }
          } else {
              update_progress(status_task, status_url);
              message = null
          }
          $(msg_destination).html(message);
      })
}

function get_selected_assets() {
  selected_assets = []
  $("input[name='review_checkbox']:checkbox:checked").each(function (index, obj) {
    selected_assets.push($(this).val());
  }); 
  return selected_assets
}

function remove_assets_from_table(assets) {
    for (const asset of assets) {
      var row = document.getElementById("#" + asset);
      row.parentNode.removeChild(row);
    }
  }

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



