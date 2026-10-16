/* KEYPOS — saved tickets. Loaded by pos.html in dependency order. */
/* Android 6 compatible — no arrow functions, no const/let */

/* ── Tickets ── */
function posLoadTickets() {
  var container = document.getElementById("ticketsList");
  if (!container) return;
  container.innerHTML = '<div style="text-align:center;padding:20px;color:#9E9E9E;">Loading...</div>';
  apiGet("/transactions/held").then(function(tickets) {
    if (!tickets || tickets.length === 0) {
      container.innerHTML = '<div style="text-align:center;padding:40px;color:#9E9E9E;">No saved tickets</div>';
      return;
    }
    var html = "";
    tickets.forEach(function(ticket) {
      var total = parseFloat(ticket.total_amount) || 0;
      var itemNames = (ticket.transaction_lines || ticket.lines || []).map(function(l) { return escapeHtml(l.product_name || "Item") + " x" + escapeHtml(l.qty); });
      var date = ticket.created_at ? localDateTime(ticket.created_at).substring(11) : "";
      html += '<div style="border:1px solid #E0E0E0;border-radius:8px;padding:12px;margin-bottom:12px;">';
      html += '<div style="font-size:13px;color:#757575;margin-bottom:4px;">' + date + ' — ' + escapeHtml(ticket.ref_number) + '</div>';
      html += '<div style="font-size:14px;margin-bottom:8px;">' + itemNames.join(", ") + '</div>';
      html += '<div style="display:flex;justify-content:space-between;align-items:center;">';
      html += '<span style="font-weight:700;font-size:16px;">' + money(total) + '</span>';
      html += '<button onclick="posResumeTicket(' + ticket.id + ')" style="background:#4CAF50;color:#fff;border:none;padding:8px 16px;border-radius:4px;font-size:14px;">RESUME</button>';
      html += '</div></div>';
    });
    container.innerHTML = html;
  }).catch(function(err) {
    if (err && err.network) { posRenderLocalTickets(container); return; }
    container.innerHTML = '<div style="text-align:center;padding:40px;color:#F44336;">Failed to load tickets</div>';
  });
}

/* Offline: show the tickets saved on this device and resume them locally. */
function posRenderLocalTickets(container) {
  DB.getTickets(function(err, tickets) {
    if (err || !tickets || tickets.length === 0) {
      container.innerHTML = '<div style="text-align:center;padding:40px;color:#9E9E9E;">No saved tickets on this device</div>';
      return;
    }
    var html = '<div style="font-size:12px;color:#FF9800;margin-bottom:8px;">Offline — showing tickets saved on this device</div>';
    tickets.forEach(function(t) {
      var names = (t.items || []).map(function(it) { return escapeHtml(it.name || "Item") + " x" + it.qty; });
      var when = t.saved_at ? localDateTime(t.saved_at).substring(11) : "";
      html += '<div style="border:1px solid #E0E0E0;border-radius:8px;padding:12px;margin-bottom:12px;">';
      html += '<div style="font-size:13px;color:#757575;margin-bottom:4px;">' + when + ' — DEVICE TICKET</div>';
      html += '<div style="font-size:14px;margin-bottom:8px;">' + names.join(", ") + '</div>';
      html += '<div style="display:flex;justify-content:space-between;align-items:center;">';
      html += '<span style="font-weight:700;font-size:13px;color:#FF9800;">OFFLINE</span>';
      html += '<button onclick="posResumeLocalTicket(' + t.id + ')" style="background:#4CAF50;color:#fff;border:none;padding:8px 16px;border-radius:4px;font-size:14px;">RESUME</button>';
      html += '</div></div>';
    });
    container.innerHTML = html;
  });
}

function posResumeLocalTicket(id) {
  if (POS_STATE.cart.length > 0 && !confirm("Replace the items in the cart with this ticket?")) return;
  DB.getTickets(function(err, tickets) {
    var ticket = null;
    for (var i = 0; i < (tickets || []).length; i++) {
      if (tickets[i].id === id) { ticket = tickets[i]; break; }
    }
    if (!ticket) { alert("Ticket not found."); return; }
    POS_STATE.cart = ticket.items || [];
    DB.deleteTicket(id, function() {});
    DB.saveCart(POS_STATE.cart, function() {});
    posRenderCart();
    closePanel("ticketsPanel");
  });
}
function posResumeTicket(ticketId) {
  if (POS_STATE.cart.length > 0 && !confirm("Replace the items in the cart with this ticket?")) return;
  resumeTransaction(ticketId).then(function(txn) {
    POS_STATE.cart = (txn.transaction_lines || []).map(function(l) {
      return {
        product_id: l.product_id,
        name: l.product_name || "Item",
        price: parseFloat(l.sell_price) || 0,
        qty: parseFloat(l.qty) || 1,
        discount: parseFloat(l.discount) || 0
      };
    });
    var lineDiscounts = 0;
    for (var i = 0; i < POS_STATE.cart.length; i++) lineDiscounts += POS_STATE.cart[i].discount;
    var afterLines = (parseFloat(txn.subtotal) || 0) - lineDiscounts;
    var cartDiscount = (parseFloat(txn.discount_amount) || 0) - lineDiscounts;
    POS_STATE.cartDiscountPct = afterLines > 0 && cartDiscount > 0 ? cartDiscount / afterLines : 0;
    DB.saveCart(POS_STATE.cart, function() {});
    posRenderCart();
    closePanel("ticketsPanel");
  }).catch(function(err) {
    alert("Failed to load ticket: " + (err.message || "Unknown error"));
  });
}
