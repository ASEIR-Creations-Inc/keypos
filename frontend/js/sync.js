/* Sync Engine — Offline Queue Push for KEYPOS */
/* Android 6 compatible — no arrow functions, no const/let */

var SYNC = (function() {

  var isSyncing = false;
  var updateHook = null;

  function isOnline() {
    return navigator.onLine;
  }

  /* Called after every sync attempt and queue change so the header badge stays true. */
  function refreshStatus() {
    DB.getQueueCounts(function(err, counts) {
      if (err || !updateHook) return;
      updateHook({
        online: isOnline(),
        pending: counts ? counts.pending : 0,
        dead: counts ? counts.dead : 0
      });
    });
  }

  function onStatusUpdate(hook) {
    updateHook = hook;
    refreshStatus();
  }

  function queueAction(actionType, payload, callback, clientRef) {
    DB.addToSyncQueue(actionType, payload, function(err, id) {
      /* Callback first: the sale confirmation must never depend on badge rendering. */
      if (callback) callback(err, id);
      if (!err) refreshStatus();
    }, clientRef);
  }

  function syncNow(callback) {
    if (isSyncing || !isOnline()) {
      if (callback) callback(null, {skipped: true});
      return;
    }
    isSyncing = true;

    DB.getPendingSync(function(err, items) {
      if (err || !items || items.length === 0) {
        isSyncing = false;
        refreshStatus();
        if (callback) callback(null, {synced: 0});
        return;
      }

      var actions = [];
      for (var i = 0; i < items.length; i++) {
        actions.push({
          action_type: items[i].action_type,
          payload: items[i].payload,
          client_ref: items[i].client_ref || null,
          auth_token: items[i].auth_token || null,
          offline_created_at: items[i].created_at || null
        });
      }

      fetch("/api/sync", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": "Bearer " + getToken()
        },
        body: JSON.stringify({device_id: DB.getDeviceId(), actions: actions})
      })
      .then(function(r) {
        if (r.status === 401) signOut();
        if (!r.ok) throw new Error("Sync request failed (" + r.status + ")");
        return r.json();
      })
      .then(function(result) {
        /* Only mark the items the server actually accepted; a client_ref makes a
           retried item safe, and rejected items stay queued for the next attempt. */
        var synced = 0;
        var failed = 0;
        var results = (result && result.results) || [];
        for (var i = 0; i < items.length; i++) {
          var outcome = null;
          for (var j = 0; j < results.length; j++) {
            if (results[j].index === i) { outcome = results[j]; break; }
          }
          if (outcome && outcome.success) {
            DB.markSynced(items[i].id, null);
            synced++;
          } else {
            DB.markFailed(items[i].id, null);
            failed++;
          }
        }
        isSyncing = false;
        refreshStatus();
        if (callback) callback(null, {synced: synced, failed: failed});
      })
      .catch(function() {
        /* Network or server error: nothing was accepted, leave the queue untouched. */
        isSyncing = false;
        refreshStatus();
        if (callback) callback(null, {skipped: true});
      });
    });
  }

  function startAutoSync(intervalSeconds) {
    var ms = (intervalSeconds || 30) * 1000;
    setInterval(function() {
      if (isOnline()) {
        syncNow(null);
      } else {
        refreshStatus();
      }
    }, ms);

    window.addEventListener("online", function() {
      refreshStatus();
      syncNow(null);
    });
    window.addEventListener("offline", function() {
      refreshStatus();
    });
  }

  function getSyncStatus(callback) {
    fetch("/api/sync/status?device_id=" + encodeURIComponent(DB.getDeviceId()), {
      headers: {
        "Authorization": "Bearer " + getToken()
      }
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (callback) callback(null, data);
    })
    .catch(function(err) {
      if (callback) callback(err);
    });
  }

  return {
    syncNow: syncNow,
    startAutoSync: startAutoSync,
    isOnline: isOnline,
    getSyncStatus: getSyncStatus,
    queueAction: queueAction,
    onStatusUpdate: onStatusUpdate,
    refreshStatus: refreshStatus
  };
})();
