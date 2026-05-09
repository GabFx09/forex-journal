// ============================================================
//  StockJournal Pro — Google Apps Script Backend
//  Buat script TERPISAH dari ForexJournal (beda spreadsheet)
//
//  CARA SETUP:
//  1. Buka sheets.new → beri nama "StockJournal Pro"
//  2. Extensions → Apps Script → hapus semua → paste kode ini → Save
//  3. Deploy → New Deployment → Web app
//     • Execute as: Me
//     • Who has access: Anyone
//  4. Deploy → izinkan → copy Web App URL
//  5. Paste URL di StockJournal Pro → Settings
// ============================================================

function doGet(e) {
  try {
    const action = e.parameter.action || '';
    const ss = SpreadsheetApp.getActiveSpreadsheet();

    // ── PING ──────────────────────────────────────────────────
    if (action === 'ping') {
      return ok({ message: 'StockJournal Pro OK', ts: new Date().toISOString() });
    }

    // ── GET ALL STOCKS ─────────────────────────────────────────
    if (action === 'getStocks') {
      const sheet = getOrCreate(ss, 'StockLog',
        ['id','date','ticker','name','action','price','qty','total','fee',
         'sector','horizon','target','sl','exchange','pe','thesis','sslink']);
      const rows = sheet.getDataRange().getValues();
      if (rows.length <= 1) return ok({ stocks: [] });
      const hdrs = rows[0];
      const stocks = rows.slice(1)
        .filter(r => r[0] !== '')
        .map(r => Object.fromEntries(hdrs.map((h, i) => [h, r[i]])));
      return ok({ stocks });
    }

    // ── GET WATCHLIST ──────────────────────────────────────────
    if (action === 'getWatchlist') {
      const sheet = getOrCreate(ss, 'Watchlist',
        ['id','ticker','name','cur','buy','sell','sector','prio','note']);
      const rows = sheet.getDataRange().getValues();
      if (rows.length <= 1) return ok({ watchlist: [] });
      const hdrs = rows[0];
      const watchlist = rows.slice(1)
        .filter(r => r[0] !== '')
        .map(r => Object.fromEntries(hdrs.map((h, i) => [h, r[i]])));
      return ok({ watchlist });
    }

    // ── GET DIVIDENS ───────────────────────────────────────────
    if (action === 'getDividens') {
      const sheet = getOrCreate(ss, 'Dividen',
        ['id','ticker','exdate','pershare','shares','amount','buyprice','yield','status','note']);
      const rows = sheet.getDataRange().getValues();
      if (rows.length <= 1) return ok({ dividens: [] });
      const hdrs = rows[0];
      const dividens = rows.slice(1)
        .filter(r => r[0] !== '')
        .map(r => Object.fromEntries(hdrs.map((h, i) => [h, r[i]])));
      return ok({ dividens });
    }

    // ── GET ALL DATA (single call) ─────────────────────────────
    if (action === 'getData') {
      const sSheet = getOrCreate(ss, 'StockLog',
        ['id','date','ticker','name','action','price','qty','total','fee',
         'sector','horizon','target','sl','exchange','pe','thesis','sslink']);
      const wSheet = getOrCreate(ss, 'Watchlist',
        ['id','ticker','name','cur','buy','sell','sector','prio','note']);
      const dSheet = getOrCreate(ss, 'Dividen',
        ['id','ticker','exdate','pershare','shares','amount','buyprice','yield','status','note']);

      const getRows = (sheet) => {
        const rows = sheet.getDataRange().getValues();
        if (rows.length <= 1) return [];
        const hdrs = rows[0];
        return rows.slice(1).filter(r => r[0] !== '')
          .map(r => Object.fromEntries(hdrs.map((h, i) => [h, r[i]])));
      };

      return ok({
        stocks:    getRows(sSheet),
        watchlist: getRows(wSheet),
        dividens:  getRows(dSheet)
      });
    }

    return ok({ error: 'Unknown action: ' + action });
  } catch(err) {
    return err_(err.toString());
  }
}

function doPost(e) {
  try {
    const payload = JSON.parse(e.postData.contents || '{}');
    const action  = payload.action || '';
    const ss      = SpreadsheetApp.getActiveSpreadsheet();

    // ── SAVE SINGLE STOCK TRANSACTION ─────────────────────────
    if (action === 'saveStock') {
      const sheet = getOrCreate(ss, 'StockLog',
        ['id','date','ticker','name','action','price','qty','total','fee',
         'sector','horizon','target','sl','exchange','pe','thesis','sslink']);
      const s = payload.stock || {};
      const rows = sheet.getDataRange().getValues();
      let found = false;
      for (let i = 1; i < rows.length; i++) {
        if (String(rows[i][0]) === String(s.id)) {
          sheet.getRange(i+1, 1, 1, 17).setValues([[
            s.id, s.date, s.ticker, s.name||'', s.action||'BUY',
            s.price||0, s.qty||0, s.total||0, s.fee||0,
            s.sector||'', s.horizon||'invest', s.target||0, s.sl||0,
            s.exchange||'NYSE', s.pe||0, s.thesis||'',
            s.sslink||''
          ]]);
          found = true; break;
        }
      }
      if (!found) {
        sheet.appendRow([
          s.id, s.date, s.ticker, s.name||'', s.action||'BUY',
          s.price||0, s.qty||0, s.total||0, s.fee||0,
          s.sector||'', s.horizon||'invest', s.target||0, s.sl||0,
          s.exchange||'NYSE', s.pe||0, s.thesis||'',
          s.sslink||''
        ]);
      }
      return ok({ status: 'saved' });
    }

    // ── DELETE SINGLE STOCK ────────────────────────────────────
    if (action === 'deleteStock') {
      const sheet = ss.getSheetByName('StockLog');
      if (sheet) {
        const rows = sheet.getDataRange().getValues();
        for (let i = rows.length - 1; i >= 1; i--) {
          if (String(rows[i][0]) === String(payload.id)) {
            sheet.deleteRow(i + 1); break;
          }
        }
      }
      return ok({ status: 'deleted' });
    }

    // ── SAVE WATCHLIST ITEM ────────────────────────────────────
    if (action === 'saveWatchlist') {
      const sheet = getOrCreate(ss, 'Watchlist',
        ['id','ticker','name','cur','buy','sell','sector','prio','note']);
      const w = payload.item || {};
      sheet.appendRow([w.id, w.ticker, w.name||'', w.cur||0, w.buy||0, w.sell||0, w.sector||'', w.prio||'med', w.note||'']);
      return ok({ status: 'saved' });
    }

    // ── DELETE WATCHLIST ITEM ──────────────────────────────────
    if (action === 'deleteWatchlist') {
      const sheet = ss.getSheetByName('Watchlist');
      if (sheet) {
        const rows = sheet.getDataRange().getValues();
        for (let i = rows.length - 1; i >= 1; i--) {
          if (String(rows[i][0]) === String(payload.id)) { sheet.deleteRow(i+1); break; }
        }
      }
      return ok({ status: 'deleted' });
    }

    // ── SAVE DIVIDEN ───────────────────────────────────────────
    if (action === 'saveDividen') {
      const sheet = getOrCreate(ss, 'Dividen',
        ['id','ticker','exdate','pershare','shares','amount','buyprice','yield','status','note']);
      const d = payload.dividen || {};
      // Check duplicate by id
      const rows = sheet.getDataRange().getValues();
      let found = false;
      for (let i = 1; i < rows.length; i++) {
        if (String(rows[i][0]) === String(d.id)) {
          sheet.getRange(i+1,1,1,10).setValues([[d.id,d.ticker,d.exdate||'',d.pershare||0,d.shares||0,d.amount||0,d.buyprice||0,d.yield||'',d.status||'expected',d.note||'']]);
          found = true; break;
        }
      }
      if (!found) sheet.appendRow([d.id,d.ticker,d.exdate||'',d.pershare||0,d.shares||0,d.amount||0,d.buyprice||0,d.yield||'',d.status||'expected',d.note||'']);
      return ok({ status: 'saved' });
    }

    // ── DELETE DIVIDEN ─────────────────────────────────────────
    if (action === 'deleteDividen') {
      const sheet = ss.getSheetByName('Dividen');
      if (sheet) {
        const rows = sheet.getDataRange().getValues();
        for (let i = rows.length - 1; i >= 1; i--) {
          if (String(rows[i][0]) === String(payload.id)) { sheet.deleteRow(i+1); break; }
        }
      }
      return ok({ status: 'deleted' });
    }

    // ── SYNC ALL (bulk) ────────────────────────────────────────
    if (action === 'syncAll') {
      // Stocks
      if (payload.stocks) {
        const sSheet = getOrCreate(ss, 'StockLog',
          ['id','date','ticker','name','action','price','qty','total','fee',
           'sector','horizon','target','sl','exchange','pe','thesis','sslink']);
        if (sSheet.getLastRow() > 1) sSheet.deleteRows(2, sSheet.getLastRow() - 1);
        if (payload.stocks.length > 0) {
          const rows = payload.stocks.map(s => [
            s.id, s.date, s.ticker, s.name||'', s.action||'BUY',
            s.price||0, s.qty||0, s.total||0, s.fee||0,
            s.sector||'', s.horizon||'invest', s.target||0, s.sl||0,
            s.exchange||'NYSE', s.pe||0, s.thesis||'',
            s.sslink||''
          ]);
          sSheet.getRange(2, 1, rows.length, 17).setValues(rows);
        }
      }
      // Watchlist
      if (payload.watchlist) {
        const wSheet = getOrCreate(ss, 'Watchlist',
          ['id','ticker','name','cur','buy','sell','sector','prio','note']);
        if (wSheet.getLastRow() > 1) wSheet.deleteRows(2, wSheet.getLastRow() - 1);
        if (payload.watchlist.length > 0) {
          const rows = payload.watchlist.map(w => [w.id,w.ticker,w.name||'',w.cur||0,w.buy||0,w.sell||0,w.sector||'',w.prio||'med',w.note||'']);
          wSheet.getRange(2, 1, rows.length, 9).setValues(rows);
        }
      }
      // Dividens
      if (payload.dividens) {
        const dSheet = getOrCreate(ss, 'Dividen',
          ['id','ticker','exdate','pershare','shares','amount','buyprice','yield','status','note']);
        if (dSheet.getLastRow() > 1) dSheet.deleteRows(2, dSheet.getLastRow() - 1);
        if (payload.dividens.length > 0) {
          const rows = payload.dividens.map(d => [d.id,d.ticker,d.exdate||'',d.pershare||0,d.shares||0,d.amount||0,d.buyprice||0,d.yield||'',d.status||'expected',d.note||'']);
          dSheet.getRange(2, 1, rows.length, 10).setValues(rows);
        }
      }
      return ok({ status: 'synced' });
    }

    return ok({ error: 'Unknown POST action: ' + action });
  } catch(err) {
    return err_(err.toString());
  }
}

// ── HELPERS ───────────────────────────────────────────────────────
function ok(data) {
  return ContentService
    .createTextOutput(JSON.stringify({ ok: true, ...data }))
    .setMimeType(ContentService.MimeType.JSON);
}

function err_(msg) {
  return ContentService
    .createTextOutput(JSON.stringify({ ok: false, error: msg }))
    .setMimeType(ContentService.MimeType.JSON);
}

function safeJson(str) {
  try { return JSON.parse(str); } catch(e) { return {}; }
}

function getOrCreate(ss, name, headers) {
  let sheet = ss.getSheetByName(name);
  if (!sheet) {
    sheet = ss.insertSheet(name);
    sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
    // Format header row
    sheet.getRange(1, 1, 1, headers.length)
      .setBackground('#1a3a5c')
      .setFontColor('#ffffff')
      .setFontWeight('bold');
    sheet.setFrozenRows(1);
  }
  return sheet;
}
