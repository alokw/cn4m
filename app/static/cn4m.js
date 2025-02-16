tailwind.config = {
    theme: {
        extend: {
            colors: {
                clifford: '#da373d',
            }
        }
    },
    fontFamily: {
        sans: ['Merriweather', 'sans-serif'],
        serif: ['Merriweather', 'serif'],
    },
}

function check_assets() {
    $.ajax({
        type: 'POST',
        url: '/check_assets',
        success: function(data, status, request) {
            status_url = request.getResponseHeader('Location');
            update_progress('check_assets', status_url);
        },
        error: function(XMLHttpRequest, textStatus, errorThrown) {
            alert(textStatus + ': ' + errorThrown);
        }
    });
}


function approve_assets() {
    selected_assets = []
    $('input:checkbox:checked').each(function() {
        selected_assets.push($(this).val());
    })
    
    console.log(selected_assets)

    $.ajax({
        type: 'POST',
        url: '/approve_assets',
        data: {
            javascript_data: JSON.stringify(selected_assets)
        },
        success: function(data, status, request) {
            status_url = request.getResponseHeader('Location');
            //update_progress('approve_assets', status_url);
        },
        error: function(XMLHttpRequest, textStatus, errorThrown) {
            alert(textStatus + ': ' + errorThrown);
        }
    });
    

    for (const asset of selected_assets) {
      var row = document.getElementById("#" + asset);
      row.parentNode.removeChild(row);
    }

}

function quarantine_assets() {
    selected_assets = []
    $('input:checkbox:checked').each(function() {
        selected_assets.push($(this).val());
    })

                for (const asset of selected_assets) {
                    parent = asset.split("\\")[0]
                    name = asset.split("\\")[1]
                    row_id = '#row' + String(hashCode(parent + "\\" + name))
                    //console.log(row_id)
                    $(row_id).remove();
                }
    $.ajax({
        type: 'POST',
        url: '/quarantine_assets',
        data: {
            javascript_data: JSON.stringify(selected_assets)
        },
        success: function(data, status, request) {
            status_url = request.getResponseHeader('Location');
            update_progress('quarantine_assets', status_url);
        },
        error: function(XMLHttpRequest, textStatus, errorThrown) {
            alert(textStatus + ': ' + errorThrown);
        }
    });
}



function hashCode(str) {
    let hash = 0;
    for (let i = 0, len = str.length; i < len; i++) {
        let chr = str.charCodeAt(i);
        hash = (hash << 5) - hash + chr;
        hash |= 0; // Convert to 32bit integer
    }
    return hash;
}

function make_ingest_folders() {
    $.ajax({
        type: 'POST',
        url: '/make_ingest_folders',
        success: function(data, status, request) {
            status_url = request.getResponseHeader('Location');
            update_progress('make_ingest_folders', status_url);
        },
        error: function(XMLHttpRequest, textStatus, errorThrown) {
            alert(textStatus + ': ' + errorThrown);
        }
    });
}


function track_assets() {
    $.ajax({
        type: 'POST',
        url: '/track_assets',
        success: function(data, status, request) {
            status_url = request.getResponseHeader('Location');
            update_progress('track_assets', status_url);
        },
        error: function(XMLHttpRequest, textStatus, errorThrown) {
            alert(textStatus + ': ' + errorThrown);
        }
    });
}





function start_long_task() {
    // add task status elements
    div = $('<div class="progress"><div></div><div>0%</div><div>...</div><div>&nbsp;</div></div><hr>');
    $('#check_asset_progress').append(div);

    // create a progress bar
    var nanobar = new Nanobar({
        bg: '#44f',
        target: div[0].childNodes[0]
    });

    // send ajax POST request to start background job
    $.ajax({
        type: 'POST',
        url: '/longtask',
        success: function(data, status, request) {
            status_url = request.getResponseHeader('Location');
            update_progress(status_url, nanobar, div[0]);
        },
        error: function() {
            alert('Unexpected error');
        }
    });
}




function update_progress(status_task, status_url) {

    if (status_task == 'check_assets') {
        // send GET request to status URL
        $.getJSON(status_url, function(data) {
            //console.log(JSON.stringify(data))
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

                <div class="grid grid-flow-col auto-cols">
                <div class="pr-4">
                <table class="mt-1 text-slate-300 text-xs table-auto text-left">
                <thead>
                <tr>
                <th class="pr-4 py-1"></th>
                <th class="pr-4">Folder</th>
                <th class="pr-4">Name</th>
                <th class="pr-4">Duration</th>
                <!--<th>Notes</th>-->
                <th class="pr-4">Codec</th>
                <th class="pr-4">Width</th>
                <th class="pr-4">Height</th>
                <th class="pr-4">FPS</th>
                <th class="pr-4">Audio</th>
                <th class="pr-4">Rate</th>
                <th class="pr-4">Bits</th>
                <th class="pr-4">Ch</th>
                <th class="pr-4">Size</th>
                <!--<th>Created</th>-->
                <!--<th>Modified</th>-->
                <!--<th>Processed</th>-->
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
                    <td class="pr-4 py-1"><input class="ml-1" type="checkbox" value="` + fileid + `"></td>
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
                </div>                              
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
                                    // rerun in 2 seconds
                                    update_progress(status_task, status_url);
                                    message = null
                /*
                setTimeout(function() {
                    update_progress(status_url);
                }, 100);
                */
            }
            $('#check_asset_progress').html(message);
            //console.log(message)
        });

    } else if (status_task == 'quarantine_assets') {
        $.getJSON(status_url, function(data) {

            percent = parseInt(data['current'] * 100 / data['total']);

            if (data['state'] == 'PENDING') {
                message = "Starting Quarantine"
                update_progress(status_task, status_url);
            } else if (data['state'] == 'PROGRESS') {
                if (data['total'] == 0) {
                    message = null
                } else {
                    message = percent + "% Complete - Quarantining Asset " + data['status']
                }
                update_progress(status_task, status_url);
            }   else if (data['status'] == 'COMPLETE') {
                message = "Quarantine Complete"

                        // remove rows that are still selected
                        selected_assets = []
                        $('input:checkbox:checked').each(function() {
                            selected_assets.push($(this).val());
                        })

                        for (const asset of selected_assets) {
                            parent = asset.split("\\")[0]
                            name = asset.split("\\")[1]
                            row_id = '#row' + String(hashCode(parent + "\\" + name))
                            //console.log(row_id)
                            $(row_id).remove();
                        }

                    }   else if (data['state'] != 'PENDING' && data['state'] != 'PROGRESS') {
                        if ('result' in data) {
                            message = 'Result: ' + data['result']
                        }   else {
                            // something unexpected happened
                            message = 'Result: ' + data['state']
                        }
                    } else {
                        update_progress(status_task, status_url);
                        message = null
                    }

                    //console.log(JSON.stringify(data))
                    $('#review_asset_progress').html(message);
                })

    } else if (status_task == 'move_assets_to_repo') {
        $.getJSON(status_url, function(data) {

            percent = parseInt(data['current'] * 100 / data['total']);

            if (data['state'] == 'PENDING') {
                message = "Moving Assets"
                update_progress(status_task, status_url);
            } else if (data['state'] == 'PROGRESS') {
                if (data['total'] == 0) {
                    message = null
                } else {
                    message = percent + "% Complete - Moving Asset " + data['status']
                }
                update_progress(status_task, status_url);
            }   else if (data['status'] == 'COMPLETE') {
                message = "Assets Moved to Repo"

                // remove rows that are still unselected
                unselected_assets = []
                $('input:checkbox:not(:checked)').each(function() {
                    unselected_assets.push($(this).val());
                })

                for (const asset of unselected_assets) {
                    parent = asset.split("\\")[0]
                    name = asset.split("\\")[1]
                    row_id = '#row' + String(hashCode(parent + "\\" + name))
                    //console.log(row_id)
                    $(row_id).remove();
                }

            }   else if (data['state'] != 'PENDING' && data['state'] != 'PROGRESS') {
                if ('result' in data) {
                    message = 'Result: ' + data['result']
                }   else {
                    // something unexpected happened
                    message = 'Result: ' + data['state']
                }
            } else {
                update_progress(status_task, status_url);
                message = null
            }

            //console.log(JSON.stringify(data))
            $('#review_asset_progress').html(message);
        })

    } else if (status_task == 'track_assets') {
        $.getJSON(status_url, function(data) {

            percent = parseInt(data['current'] * 100 / data['total']);

            if (data['state'] == 'PENDING') {
                message = "Tracking Assets"
                update_progress(status_task, status_url);
            } else if (data['state'] == 'PROGRESS') {
                if (data['total'] == 0) {
                    message = null
                } else {
                    message = percent + "% Complete - Tracking Asset " + data['status']
                }
                update_progress(status_task, status_url);
            } else if (data['status'] == 'COMPLETE') {
                message = "Assets pushed to tracker."

            } else if (data['state'] != 'PENDING' && data['state'] != 'PROGRESS') {
                if ('result' in data) {
                    message = 'Result: ' + data['result']
                } else {
                    // something unexpected happened
                    message = 'Result: ' + data['state']
                }
            } else {
                update_progress(status_task, status_url);
                message = null
            }

            $('#track_assets_progress').html(message);
        })

    } else if (status_task == 'make_ingest_folders') {
        $.getJSON(status_url, function(data) {

            percent = parseInt(data['current'] * 100 / data['total']);

            if (data['state'] == 'PENDING') {
                message = "Creating Folders"
                update_progress(status_task, status_url);
            } else if (data['state'] == 'PROGRESS') {
                if (data['total'] == 0) {
                    message = null
                } else {
                    message = percent + "% Complete - Creating Folder " + data['status']
                }
                update_progress(status_task, status_url);
            } else if (data['status'] == 'COMPLETE') {
                message = "Ingest Folders Created."

            } else if (data['state'] != 'PENDING' && data['state'] != 'PROGRESS') {
                if ('result' in data) {
                    message = 'Result: ' + data['result']
                } else {
                    // something unexpected happened
                    message = 'Result: ' + data['state']
                }
            } else {
                update_progress(status_task, status_url);
                message = null
            }

            $('#utility_progress').html(message);
        })
    }

}

function unselect_all() {
    $('input:checkbox(:checked)').each(function() {
        $(this).prop("checked", false);
    })
}

function select_all() {
    $('input:checkbox:not(:checked)').each(function() {
        $(this).prop("checked", true);
    })
}

function move_assets_to_repo() {
    unselected_assets = []
    $('input:checkbox:not(:checked)').each(function() {
        unselected_assets.push($(this).val());
    })

    $.ajax({
        type: 'POST',
        url: '/move_assets_to_repo',
        data: {
            javascript_data: JSON.stringify(unselected_assets)
        },
        success: function(data, status, request) {
            status_url = request.getResponseHeader('Location');
            update_progress('move_assets_to_repo', status_url);
        },
        error: function(XMLHttpRequest, textStatus, errorThrown) {
            alert(textStatus + ': ' + errorThrown);
        }
    });

}
