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
            asset_table = `
            <div class="table-responsive">
            <table class="table table-dark table-striped table-hover table-sm fs-8 fw-lighter">
            <thead>
            <tr>
            <th class="pr-4 py-1"><input type="checkbox" onClick="toggle_checkboxes(this)" /></th>
            <th class="pr-4">Folder</th>
            <th class="pr-4">Name</th>
            <th class="pr-4">Duration</th>
            <th class="pr-4">Codec</th>
            <th class="pr-4">Width</th>
            <th class="pr-4">Height</th>
            <th class="pr-4">FPS</th>
            <th class="pr-4">Audio</th>
            <th class="pr-4">Rate</th>
            <th class="pr-4">Bits</th>
            <th class="pr-4">Ch</th>
            <th class="pr-4">Size</th>
            </tr>
            </thead>
            <tbody>`
            
            for (const [key, value] of Object.entries(data['result'])) {
                obj = data['result'][key]
                fileid = key
                name = (('name' in obj) ? obj['name'] : "")
                parent = (('parent' in obj) ? obj['parent'] : "").replace(/ /g, '&nbsp;')
                duration = ('duration' in obj) ? obj['duration'] : ""
                video_codec = ('video_codec' in obj) ? obj['video_codec'] : ""
                width = ('width' in obj) ? obj['width'] : ""
                height = ('height' in obj) ? obj['height'] : ""
                framerate = ('framerate' in obj) ? obj['framerate'] : ""
                audio = ('audio' in obj) ? obj['audio'] : ""
                audio_rate = ('audio_rate' in obj) ? obj['audio_rate'] : ""
                audio_bits = ('audio_bits' in obj) ? obj['audio_bits'] : ""
                audio_channels = ('audio_channels' in obj) ? obj['audio_channels'] : ""
                size = ('size' in obj) ? obj['size'] : ""

                asset_table = asset_table + `
                <tr id=#` + fileid + ` class="even:bg-zinc-800 odd:bg-zinc-900 text-slate-300 hover:bg-zinc-700">
                <td class="pr-4 py-1"><input name="review_checkbox" type="checkbox" value="` + fileid + `"></td>
                <td class="pr-4">` + parent + `</td>
                <td class="pr-4">` + name + `</td>
                <td class="pr-4">` + duration + `</td>
                <td class="pr-4">` + video_codec + `</td>
                <td class="pr-4">` + width + `</td>
                <td class="pr-4">` + height + `</td>
                <td class="pr-4">` + framerate + `</td>
                <td class="pr-4">` + audio + `</td>
                <td class="pr-4">` + audio_rate + `</td>
                <td class="pr-4">` + audio_bits + `</td>
                <td class="pr-4">` + audio_channels + `</td>
                <td class="pr-4">` + size + `</td>
                </tr>`
            }

            asset_table = asset_table + `
            </tbody>
            </table>
            </div>`

            $('#results').html(asset_table);

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



