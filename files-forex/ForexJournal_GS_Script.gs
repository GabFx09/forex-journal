// ============================================================
//  ForexJournal Pro — Google Apps Script Backend
//  v3.0 — Clean rewrite, termasuk Google Drive screenshot
//
//  CARA SETUP:
//  1. Buka Google Sheet kamu → Extensions → Apps Script
//  2. Hapus semua kode lama → paste seluruh kode ini → Ctrl+S
//  3. Deploy → New Deployment → Web app
//     • Execute as  : Me
//     • Who has access: Anyone
//  4. Klik Deploy → izinkan semua permission → copy Web App URL
//  5. Paste URL di jurnal → Settings → Test → Sambungkan
//
//  PENTING: Setiap update script, Deploy ulang dengan
//  "New Deployment" (bukan manage existing deployment)
// ============================================================

// ══════════════════════════════════════════════════════════════
//  GET — Ambil data dari Sheets
// ══════════════════════════════════════════════════════════════
function doGet(e) {
  try {
    const action = (e.parameter.action || '').trim();
    const ss = SpreadsheetApp.getActiveSpreadsheet();

    // Ping — cek koneksi
    if (action === 'ping') {
      return ok({ status: 'connected', version: '3.0', time: new Date().toISOString() });
    }

    // Ambil semua trade
    if (action === 'getTrades') {
      const sheet = getOrCreate(ss, 'TradeLog', TRADE_HEADERS);
      const rows  = sheet.getDataRange().getValues();
      if (rows.length <= 1) return ok({ trades: [] });
      const hdrs   = rows[0];
      const trades = rows.slice(1)
        .filter(r => r[0] !== '' && r[0] !== null && r[0] !== undefined)
        .map(r => Object.fromEntries(hdrs.map((h, i) => [h, fmtCell(ss, h, r[i])])));
      return ok({ trades });
    }

    // Ambil semua planning (harian + mingguan)
    if (action === 'getPlanning') {
      const sheet = getOrCreate(ss, 'Planning', ['type','savedAt','json']);
      const rows  = sheet.getDataRange().getValues();
      if (rows.length <= 1) return ok({ items: [] });
      const items = rows.slice(1)
        .filter(r => r[0] !== '')
        .map(r => ({ type: r[0], savedAt: r[1], data: safeJson(r[2]) }));
      return ok({ items });
    }

    // Ambil riwayat psikologi
    if (action === 'getPsyLogs') {
      const sheet = ss.getSheetByName('PsyLog');
      if (!sheet || sheet.getLastRow() <= 1) return ok({ logs: [] });
      const rows = sheet.getDataRange().getValues();
      const hdrs = rows[0];
      const logs = rows.slice(1)
        .filter(r => r[0] !== '')
        .map(r => Object.fromEntries(hdrs.map((h, i) => [h, r[i]])));
      return ok({ logs });
    }

    // Ambil semua transaksi (depo/wd)
    if (action === 'getTransactions') {
      const sheet = ss.getSheetByName('Transaksi');
      if (!sheet || sheet.getLastRow() <= 1) return ok({ transactions: [] });
      const rows = sheet.getDataRange().getValues();
      const hdrs = rows[0];
      const transactions = rows.slice(1)
        .filter(r => r[0] !== '')
        .map(r => Object.fromEntries(hdrs.map((h, i) => [h, fmtCell(ss, h, r[i])])));
      return ok({ transactions });
    }

    return ok({ status: 'ok', message: 'ForexJournal GS Script berjalan' });

  } catch(err) {
    return fail(err.message);
  }
}

// ══════════════════════════════════════════════════════════════
//  POST — Simpan / hapus / sync data
// ══════════════════════════════════════════════════════════════
function doPost(e) {
  try {
    const payload = JSON.parse(e.postData.contents || '{}');
    const action  = (payload.action || '').trim();
    const ss      = SpreadsheetApp.getActiveSpreadsheet();

    // ── SCREENSHOT: Upload ke Google Drive ─────────────────────
    if (action === 'saveScreenshot') {
      const base64Full = payload.base64 || '';
      if (!base64Full) return fail('No image data');

      const tradeId = String(payload.tradeId || Date.now());
      const pair    = (payload.pair || 'TRADE').replace(/[^A-Z0-9]/g, '').substring(0, 10);

      // Pisah header & data base64
      const commaIdx = base64Full.indexOf(',');
      const header   = commaIdx > -1 ? base64Full.substring(0, commaIdx) : '';
      const b64data  = commaIdx > -1 ? base64Full.substring(commaIdx + 1) : base64Full;
      const mimeMatch = header.match(/:(.*?);/);
      const mimeType = mimeMatch ? mimeMatch[1] : 'image/jpeg';
      const ext      = mimeType.split('/')[1] || 'jpg';
      const filename = 'FX_' + pair + '_' + tradeId + '.' + ext;

      // Cari / buat folder di Drive
      const folderIter = DriveApp.getFoldersByName('ForexJournal Screenshots');
      const folder = folderIter.hasNext()
        ? folderIter.next()
        : DriveApp.createFolder('ForexJournal Screenshots');

      // Decode → blob → simpan ke Drive
      const decoded = Utilities.base64Decode(b64data);
      const blob    = Utilities.newBlob(decoded, mimeType, filename);
      const file    = folder.createFile(blob);

      // Izin: siapapun dengan link bisa lihat (tidak perlu login)
      file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);

      const fileId  = file.getId();
      const viewUrl = 'https://drive.google.com/uc?export=view&id=' + fileId;
      const pageUrl = 'https://drive.google.com/file/d/' + fileId + '/view';

      return ok({ fileId, viewUrl, pageUrl, filename });
    }

    // ── SCREENSHOT: Hapus dari Google Drive ────────────────────
    if (action === 'deleteScreenshot') {
      try {
        if (payload.fileId) {
          DriveApp.getFileById(payload.fileId).setTrashed(true);
        }
      } catch(e2) { /* file sudah dihapus atau tidak ditemukan */ }
      return ok({ status: 'deleted' });
    }

    // ── TRADE: Simpan 1 trade ───────────────────────────────────
    if (action === 'saveTrade') {
      const sheet = getOrCreate(ss, 'TradeLog', TRADE_HEADERS);
      const t     = payload.trade || {};
      const rows  = sheet.getDataRange().getValues();
      let found   = false;

      for (let i = 1; i < rows.length; i++) {
        if (String(rows[i][0]) === String(t.id)) {
          sheet.getRange(i+1, 1, 1, 14).setValues([tradeRow(t)]);
          found = true;
          break;
        }
      }
      if (!found) sheet.appendRow(tradeRow(t));
      return ok({ status: 'saved' });
    }

    // ── TRADE: Hapus 1 trade ────────────────────────────────────
    if (action === 'deleteTrade') {
      const sheet = ss.getSheetByName('TradeLog');
      if (sheet) {
        const rows = sheet.getDataRange().getValues();
        for (let i = rows.length - 1; i >= 1; i--) {
          if (String(rows[i][0]) === String(payload.id)) {
            sheet.deleteRow(i + 1);
            break;
          }
        }
      }
      return ok({ status: 'deleted' });
    }

    // ── TRADE: Hapus semua trade ────────────────────────────────
    if (action === 'clearTrades') {
      const sheet = ss.getSheetByName('TradeLog');
      if (sheet && sheet.getLastRow() > 1) {
        sheet.deleteRows(2, sheet.getLastRow() - 1);
      }
      return ok({ status: 'cleared' });
    }

    // ── TRADE: Sync semua (bulk replace) ───────────────────────
    if (action === 'syncAll') {
      const sheet  = getOrCreate(ss, 'TradeLog', TRADE_HEADERS);
      if (sheet.getLastRow() > 1) sheet.deleteRows(2, sheet.getLastRow() - 1);
      const trades = payload.trades || [];
      if (trades.length > 0) {
        const rows = trades.map(t => tradeRow(t));
        sheet.getRange(2, 1, rows.length, 14).setValues(rows);
      }
      return ok({ status: 'synced', count: trades.length });
    }

    // ── PLANNING: Simpan 1 entri (id-based, tidak timpa) ───────
    if (action === 'savePlan') {
      const sheet = getOrCreate(ss, 'Planning', ['type','savedAt','json']);
      const p     = payload.data || {};
      const rows  = sheet.getDataRange().getValues();
      let found   = false;

      if (p.id) {
        for (let i = 1; i < rows.length; i++) {
          const existing = safeJson(rows[i][2]);
          if (String(existing.id) === String(p.id)) {
            sheet.getRange(i+1, 1, 1, 3).setValues([
              [payload.planType, new Date().toISOString(), JSON.stringify(p)]
            ]);
            found = true;
            break;
          }
        }
      }
      if (!found) {
        sheet.appendRow([payload.planType, new Date().toISOString(), JSON.stringify(p)]);
      }
      return ok({ status: 'saved' });
    }

    // ── PLANNING: Hapus 1 entri (by id) ────────────────────────
    if (action === 'deletePlanEntry') {
      const sheet = ss.getSheetByName('Planning');
      if (sheet) {
        const rows = sheet.getDataRange().getValues();
        for (let i = rows.length - 1; i >= 1; i--) {
          const rd = safeJson(rows[i][2]);
          if (String(rd.id) === String(payload.id) && rows[i][0] === payload.planType) {
            sheet.deleteRow(i + 1);
            break;
          }
        }
      }
      return ok({ status: 'deleted' });
    }

    // ── PLANNING: Hapus semua berdasarkan type ──────────────────
    if (action === 'clearAllPlans') {
      const sheet = ss.getSheetByName('Planning');
      if (sheet && sheet.getLastRow() > 1) {
        const rows = sheet.getDataRange().getValues();
        for (let i = rows.length - 1; i >= 1; i--) {
          if (rows[i][0] === payload.planType) sheet.deleteRow(i + 1);
        }
      }
      return ok({ status: 'cleared' });
    }

    // ── PLANNING: Hapus semua berdasarkan type (alias) ──────────
    if (action === 'deletePlan') {
      const sheet = ss.getSheetByName('Planning');
      if (sheet && sheet.getLastRow() > 1) {
        const rows = sheet.getDataRange().getValues();
        for (let i = rows.length - 1; i >= 1; i--) {
          if (rows[i][0] === payload.planType) sheet.deleteRow(i + 1);
        }
      }
      return ok({ status: 'deleted' });
    }

    // ── PSIKOLOGI: Simpan 1 log ─────────────────────────────────
    if (action === 'savePsyLog') {
      const sheet = getOrCreate(ss, 'PsyLog', PSY_HEADERS);
      const p     = payload.entry || {};
      const rows  = sheet.getDataRange().getValues();
      let found   = false;

      for (let i = 1; i < rows.length; i++) {
        if (String(rows[i][0]) === String(p.id) || rows[i][1] === p.date) {
          sheet.getRange(i+1, 1, 1, 13).setValues([psyRow(p)]);
          found = true;
          break;
        }
      }
      if (!found) sheet.appendRow(psyRow(p));
      return ok({ status: 'saved' });
    }

    // ── PSIKOLOGI: Hapus 1 log ──────────────────────────────────
    if (action === 'deletePsyLog') {
      const sheet = ss.getSheetByName('PsyLog');
      if (sheet) {
        const rows = sheet.getDataRange().getValues();
        for (let i = rows.length - 1; i >= 1; i--) {
          if (String(rows[i][0]) === String(payload.id)) {
            sheet.deleteRow(i + 1);
            break;
          }
        }
      }
      return ok({ status: 'deleted' });
    }

    // ── PSIKOLOGI: Hapus semua log ──────────────────────────────
    if (action === 'clearPsyLogs') {
      const sheet = ss.getSheetByName('PsyLog');
      if (sheet && sheet.getLastRow() > 1) {
        sheet.deleteRows(2, sheet.getLastRow() - 1);
      }
      return ok({ status: 'cleared' });
    }

    // ── PSIKOLOGI: Sync semua log (bulk) ───────────────────────
    if (action === 'syncPsyLogs') {
      const sheet = getOrCreate(ss, 'PsyLog', PSY_HEADERS);
      if (sheet.getLastRow() > 1) sheet.deleteRows(2, sheet.getLastRow() - 1);
      const logs = payload.logs || [];
      if (logs.length > 0) {
        const rows = logs.map(p => psyRow(p));
        sheet.getRange(2, 1, rows.length, 13).setValues(rows);
      }
      return ok({ status: 'synced', count: logs.length });
    }

    // ── TRANSAKSI: Simpan 1 transaksi ─────────────────────────────
    if (action === 'saveTxn') {
      const sheet = getOrCreate(ss, 'Transaksi', TXN_HEADERS);
      const t     = payload.txn || {};
      const rows  = sheet.getDataRange().getValues();
      let found   = false;
      for (let i = 1; i < rows.length; i++) {
        if (String(rows[i][0]) === String(t.id)) {
          sheet.getRange(i+1, 1, 1, TXN_HEADERS.length).setValues([txnRow(t)]);
          found = true;
          break;
        }
      }
      if (!found) sheet.appendRow(txnRow(t));
      return ok({ status: 'saved' });
    }

    // ── TRANSAKSI: Hapus 1 transaksi ──────────────────────────────
    if (action === 'deleteTxn') {
      const sheet = ss.getSheetByName('Transaksi');
      if (sheet) {
        const rows = sheet.getDataRange().getValues();
        for (let i = rows.length - 1; i >= 1; i--) {
          if (String(rows[i][0]) === String(payload.id)) {
            sheet.deleteRow(i + 1);
            break;
          }
        }
      }
      return ok({ status: 'deleted' });
    }

    // ── TRANSAKSI: Hapus semua transaksi ──────────────────────────
    if (action === 'clearTxns') {
      const sheet = ss.getSheetByName('Transaksi');
      if (sheet && sheet.getLastRow() > 1) {
        sheet.deleteRows(2, sheet.getLastRow() - 1);
      }
      return ok({ status: 'cleared' });
    }

    // ── TRANSAKSI: Sync semua (bulk replace) ──────────────────────
    if (action === 'syncTxns') {
      const sheet = getOrCreate(ss, 'Transaksi', TXN_HEADERS);
      if (sheet.getLastRow() > 1) sheet.deleteRows(2, sheet.getLastRow() - 1);
      const txns = payload.transactions || [];
      if (txns.length > 0) {
        const rows = txns.map(t => txnRow(t));
        sheet.getRange(2, 1, rows.length, TXN_HEADERS.length).setValues(rows);
      }
      return ok({ status: 'synced', count: txns.length });
    }

    return ok({ status: 'unknown action', action });

  } catch(err) {
    return fail(err.message);
  }
}

// ══════════════════════════════════════════════════════════════
//  KONSTANTA HEADER KOLOM
// ══════════════════════════════════════════════════════════════
const TRADE_HEADERS = [
  'id','date','pair','dir','entry','sl','tp',
  'lot','setup','session','result','pnl','note',
  'sslink'
];

const TXN_HEADERS = ['id','date','type','amount','method','note'];

const PSY_HEADERS = [
  'id','date','mood','fokus','emosi','disiplin',
  'pd','fomo','istirahat','score','feel','lesson','savedAt'
];

// ══════════════════════════════════════════════════════════════
//  ROW BUILDER — pastikan urutan kolom selalu konsisten
// ══════════════════════════════════════════════════════════════
function tradeRow(t) {
  return [
    t.id        || '',
    t.date      || '',
    t.pair      || '',
    t.dir       || '',
    t.entry     || '',
    t.sl        || '',
    t.tp        || '',
    t.lot       || '',
    t.setup     || '',
    t.session   || '',
    t.result    || '',
    t.pnl       || '',
    t.note      || '',
    t.sslink    || ''
  ];
}

function txnRow(t) {
  return [
    t.id     || '',
    t.date   || '',
    t.type   || '',
    t.amount || '',
    t.method || '',
    t.note   || ''
  ];
}

function psyRow(p) {
  return [
    p.id       || '',
    p.date     || '',
    p.mood     || '',
    p.fokus    || 0,
    p.emosi    || 0,
    p.disiplin || 0,
    p.pd       || 0,
    p.fomo     || 0,
    p.istirahat|| 0,
    p.score    || 0,
    p.feel     || '',
    p.lesson   || '',
    p.savedAt  || ''
  ];
}

// ══════════════════════════════════════════════════════════════
//  HELPERS
// ══════════════════════════════════════════════════════════════
// Sheets otomatis mengubah cell "yyyy-MM-dd" jadi tipe Date — kalau dibaca
// lewat getValues() lalu di-String()-kan apa adanya, hasilnya jadi string
// GMT panjang yang merusak parsing tanggal di sisi klien (kalender P&L).
// Helper ini mengubahnya balik ke "yyyy-MM-dd" khusus utk kolom 'date'.
function fmtCell(ss, header, v) {
  if (v instanceof Date) {
    return header === 'date'
      ? Utilities.formatDate(v, ss.getSpreadsheetTimeZone(), 'yyyy-MM-dd')
      : v.toISOString();
  }
  return String(v ?? '');
}

function getOrCreate(ss, name, headers) {
  let sheet = ss.getSheetByName(name);
  if (!sheet) {
    sheet = ss.insertSheet(name);
    sheet.appendRow(headers);
    const hRange = sheet.getRange(1, 1, 1, headers.length);
    hRange.setBackground('#0D1B2A');
    hRange.setFontColor('#F0B429');
    hRange.setFontWeight('bold');
    sheet.setFrozenRows(1);
  }
  return sheet;
}

function ok(data) {
  return ContentService
    .createTextOutput(JSON.stringify({ ok: true, ...data }))
    .setMimeType(ContentService.MimeType.JSON);
}

function fail(msg) {
  return ContentService
    .createTextOutput(JSON.stringify({ ok: false, error: msg }))
    .setMimeType(ContentService.MimeType.JSON);
}

function safeJson(str) {
  try { return JSON.parse(str); } catch(e) { return {}; }
}
