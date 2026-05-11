// ============================================================
//  FinanceJournal Pro — Google Apps Script Backend
//  v1.0
//
//  CARA SETUP:
//  1. Buka sheets.new → beri nama "FinanceJournal Pro"
//  2. Extensions → Apps Script → hapus semua → paste kode ini → Save
//  3. Deploy → New Deployment → Web app
//     • Execute as  : Me
//     • Who has access: Anyone
//  4. Klik Deploy → Allow → copy Web App URL
//  5. Buka FinanceJournal_Pro.html → klik 🔗 Hubungkan Sheets → paste URL
// ============================================================

function doGet(e) {
  try {
    const action = (e.parameter.action || '').trim();
    const ss = SpreadsheetApp.getActiveSpreadsheet();

    // ── PING ────────────────────────────────────────────────
    if (action === 'ping') {
      return ok({ status: 'connected', app: 'FinanceJournal Pro', version: '1.0' });
    }

    // ── GET ALL DATA (single call) ───────────────────────────
    if (action === 'getData') {
      return ok({
        transactions: getSheetData(ss, 'Transaksi',  TRX_HEADERS),
        budgets:      getBudgets(ss),
        debts:        getSheetData(ss, 'Hutang',     DEBT_HEADERS),
        goals:        getSheetData(ss, 'Tujuan',     GOAL_HEADERS),
        assets:       getSheetData(ss, 'Aset',       ASSET_HEADERS),
        profile:      getProfile(ss),
      });
    }

    // ── GET TRANSAKSI ────────────────────────────────────────
    if (action === 'getTrx') {
      return ok({ transactions: getSheetData(ss, 'Transaksi', TRX_HEADERS) });
    }

    return ok({ status: 'ok', message: 'FinanceJournal GS berjalan' });

  } catch(err) {
    return fail(err.message);
  }
}

function doPost(e) {
  try {
    const payload = JSON.parse(e.postData.contents || '{}');
    const action  = (payload.action || '').trim();
    const ss      = SpreadsheetApp.getActiveSpreadsheet();

    // ── SAVE TRANSAKSI ───────────────────────────────────────
    if (action === 'saveTrx') {
      const sheet = getOrCreate(ss, 'Transaksi', TRX_HEADERS);
      const t = payload.trx || {};
      upsertRow(sheet, t.id, trxRow(t));
      return ok({ status: 'saved' });
    }

    // ── DELETE TRANSAKSI ─────────────────────────────────────
    if (action === 'deleteTrx') {
      deleteRowById(ss, 'Transaksi', payload.id);
      return ok({ status: 'deleted' });
    }

    // ── SAVE HUTANG ──────────────────────────────────────────
    if (action === 'saveDebt') {
      const sheet = getOrCreate(ss, 'Hutang', DEBT_HEADERS);
      const d = payload.debt || {};
      upsertRow(sheet, d.id, debtRow(d));
      return ok({ status: 'saved' });
    }

    // ── DELETE HUTANG ────────────────────────────────────────
    if (action === 'deleteDebt') {
      deleteRowById(ss, 'Hutang', payload.id);
      return ok({ status: 'deleted' });
    }

    // ── SAVE TUJUAN ──────────────────────────────────────────
    if (action === 'saveGoal') {
      const sheet = getOrCreate(ss, 'Tujuan', GOAL_HEADERS);
      const g = payload.goal || {};
      upsertRow(sheet, g.id, goalRow(g));
      return ok({ status: 'saved' });
    }

    // ── DELETE TUJUAN ────────────────────────────────────────
    if (action === 'deleteGoal') {
      deleteRowById(ss, 'Tujuan', payload.id);
      return ok({ status: 'deleted' });
    }

    // ── SAVE ASET ────────────────────────────────────────────
    if (action === 'saveAsset') {
      const sheet = getOrCreate(ss, 'Aset', ASSET_HEADERS);
      const a = payload.asset || {};
      upsertRow(sheet, a.id, assetRow(a));
      return ok({ status: 'saved' });
    }

    // ── DELETE ASET ──────────────────────────────────────────
    if (action === 'deleteAsset') {
      deleteRowById(ss, 'Aset', payload.id);
      return ok({ status: 'deleted' });
    }

    // ── SAVE ANGGARAN ────────────────────────────────────────
    if (action === 'saveBudget') {
      saveBudgetData(ss, payload.month, payload.data);
      return ok({ status: 'saved' });
    }

    // ── SAVE PROFIL ──────────────────────────────────────────
    if (action === 'saveProfile') {
      saveProfileData(ss, payload.profile);
      return ok({ status: 'saved' });
    }

    // ── SYNC ALL (bulk replace) ──────────────────────────────
    if (action === 'syncAll') {
      // Transaksi
      if (payload.transactions) {
        const s = getOrCreate(ss, 'Transaksi', TRX_HEADERS);
        clearDataRows(s);
        if (payload.transactions.length > 0) {
          s.getRange(2, 1, payload.transactions.length, TRX_HEADERS.length)
           .setValues(payload.transactions.map(t => trxRow(t)));
        }
      }
      // Hutang
      if (payload.debts) {
        const s = getOrCreate(ss, 'Hutang', DEBT_HEADERS);
        clearDataRows(s);
        if (payload.debts.length > 0) {
          s.getRange(2, 1, payload.debts.length, DEBT_HEADERS.length)
           .setValues(payload.debts.map(d => debtRow(d)));
        }
      }
      // Tujuan
      if (payload.goals) {
        const s = getOrCreate(ss, 'Tujuan', GOAL_HEADERS);
        clearDataRows(s);
        if (payload.goals.length > 0) {
          s.getRange(2, 1, payload.goals.length, GOAL_HEADERS.length)
           .setValues(payload.goals.map(g => goalRow(g)));
        }
      }
      // Aset
      if (payload.assets) {
        const s = getOrCreate(ss, 'Aset', ASSET_HEADERS);
        clearDataRows(s);
        if (payload.assets.length > 0) {
          s.getRange(2, 1, payload.assets.length, ASSET_HEADERS.length)
           .setValues(payload.assets.map(a => assetRow(a)));
        }
      }
      // Anggaran
      if (payload.budgets) {
        Object.entries(payload.budgets).forEach(([month, data]) => {
          saveBudgetData(ss, month, data);
        });
      }
      // Profil
      if (payload.profile) {
        saveProfileData(ss, payload.profile);
      }
      return ok({ status: 'synced' });
    }

    return ok({ status: 'unknown action', action });

  } catch(err) {
    return fail(err.message);
  }
}

// ══════════════════════════════════════════════════════════════
//  HEADERS
// ══════════════════════════════════════════════════════════════
const TRX_HEADERS   = ['id','date','type','cat','amount','desc','method','recur','note','rekKey'];
const DEBT_HEADERS  = ['id','name','type','original','remaining','payment','rate','due','note'];
const GOAL_HEADERS  = ['id','name','icon','target','current','deadline','color','note'];
const ASSET_HEADERS = ['id','name','cat','value','date','note'];

// ══════════════════════════════════════════════════════════════
//  ROW BUILDERS
// ══════════════════════════════════════════════════════════════
function trxRow(t) {
  return [t.id||'', t.date||'', t.type||'', t.cat||'', t.amount||0, t.desc||'', t.method||'', t.recur||'', t.note||'', t.rekKey||''];
}
function debtRow(d) {
  return [d.id||'', d.name||'', d.type||'', d.original||0, d.remaining||0, d.payment||0, d.rate||0, d.due||'', d.note||''];
}
function goalRow(g) {
  return [g.id||'', g.name||'', g.icon||'🎯', g.target||0, g.current||0, g.deadline||'', g.color||'grn', g.note||''];
}
function assetRow(a) {
  return [a.id||'', a.name||'', a.cat||'', a.value||0, a.date||'', a.note||''];
}

// ══════════════════════════════════════════════════════════════
//  ANGGARAN — disimpan di sheet "Anggaran" per baris per bulan
// ══════════════════════════════════════════════════════════════
function saveBudgetData(ss, month, data) {
  const sheet = getOrCreate(ss, 'Anggaran', ['month','key','value']);
  // Hapus baris lama untuk bulan ini
  const rows = sheet.getDataRange().getValues();
  for (let i = rows.length - 1; i >= 1; i--) {
    if (String(rows[i][0]) === String(month)) sheet.deleteRow(i + 1);
  }
  // Tambah baris baru
  Object.entries(data || {}).forEach(([k, v]) => {
    sheet.appendRow([month, k, v]);
  });
}

function getBudgets(ss) {
  const sheet = ss.getSheetByName('Anggaran');
  if (!sheet || sheet.getLastRow() <= 1) return {};
  const rows = sheet.getDataRange().getValues().slice(1);
  const result = {};
  rows.forEach(r => {
    const month = String(r[0]), key = String(r[1]), val = r[2];
    if (!result[month]) result[month] = {};
    result[month][key] = typeof val === 'number' ? val : parseFloat(val) || val;
  });
  return result;
}

// ══════════════════════════════════════════════════════════════
//  PROFIL — disimpan di sheet "Profil"
// ══════════════════════════════════════════════════════════════
function saveProfileData(ss, profile) {
  const sheet = getOrCreate(ss, 'Profil', ['key','value']);
  // Hapus semua data lama
  if (sheet.getLastRow() > 1) sheet.deleteRows(2, sheet.getLastRow() - 1);
  Object.entries(profile || {}).forEach(([k, v]) => {
    sheet.appendRow([k, v]);
  });
}

function getProfile(ss) {
  const sheet = ss.getSheetByName('Profil');
  if (!sheet || sheet.getLastRow() <= 1) return {};
  const rows = sheet.getDataRange().getValues().slice(1);
  const result = {};
  rows.forEach(r => { result[String(r[0])] = r[1]; });
  return result;
}

// ══════════════════════════════════════════════════════════════
//  HELPERS
// ══════════════════════════════════════════════════════════════
function getSheetData(ss, name, headers) {
  const sheet = getOrCreate(ss, name, headers);
  const rows = sheet.getDataRange().getValues();
  if (rows.length <= 1) return [];
  const hdrs = rows[0];
  return rows.slice(1)
    .filter(r => r[0] !== '' && r[0] !== null && r[0] !== undefined)
    .map(r => Object.fromEntries(hdrs.map((h, i) => [h, r[i]])));
}

function upsertRow(sheet, id, rowData) {
  const rows = sheet.getDataRange().getValues();
  for (let i = 1; i < rows.length; i++) {
    if (String(rows[i][0]) === String(id)) {
      sheet.getRange(i + 1, 1, 1, rowData.length).setValues([rowData]);
      return;
    }
  }
  sheet.appendRow(rowData);
}

function deleteRowById(ss, sheetName, id) {
  const sheet = ss.getSheetByName(sheetName);
  if (!sheet) return;
  const rows = sheet.getDataRange().getValues();
  for (let i = rows.length - 1; i >= 1; i--) {
    if (String(rows[i][0]) === String(id)) { sheet.deleteRow(i + 1); break; }
  }
}

function clearDataRows(sheet) {
  if (sheet.getLastRow() > 1) sheet.deleteRows(2, sheet.getLastRow() - 1);
}

function getOrCreate(ss, name, headers) {
  let sheet = ss.getSheetByName(name);
  if (!sheet) {
    sheet = ss.insertSheet(name);
    sheet.appendRow(headers);
    const r = sheet.getRange(1, 1, 1, headers.length);
    r.setBackground('#0D1B2A');
    r.setFontColor('#00C896');
    r.setFontWeight('bold');
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
