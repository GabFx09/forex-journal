# ARCHIVED — historical one-time patch script.
#
# This already ran successfully against FinanceJournal_Pro.html: the "rekening"
# (bank/e-wallet balance) feature it injects is already present in
# files-finance/FinanceJournal_Pro.html. Do not re-run as-is — the hardcoded
# `path` below (C:\PROJECT-FINANCE\...) no longer matches this repo's layout
# (files-finance/FinanceJournal_Pro.html), and re-running would just report
# "GAGAL" for every replacement since the original (pre-patch) strings it
# searches for no longer exist in the file.
#
# Kept for reference only, in case a similar string-replace patch pattern is
# needed again in the future.

import re

path = r'C:\PROJECT-FINANCE\files-finance\FinanceJournal_Pro.html'
with open(path, 'r', encoding='utf-8') as f:
    html = f.read()

def rep(old, new, label):
    global html
    if old in html:
        html = html.replace(old, new, 1)
        print(f'  OK: {label}')
    else:
        print(f'  GAGAL: {label}')

# ── 1. Tambah state rekening ──────────────────────────────────────
rep(
    "let GS_URL       = lsGet('fj_gs_url','');",
    "let GS_URL       = lsGet('fj_gs_url','');\nlet rekening     = lsGet('fj_rekening',{BNI:0,JAGO:0,BRI:0,MANDIRI:0,BCA:0,DANA:0,GOPAY:0,OVO:0,LINKAJA:0});",
    "Tambah state rekening"
)

# ── 2. Update save() ──────────────────────────────────────────────
rep(
    "  lsSet('fj_profile',profile);\n}",
    "  lsSet('fj_profile',profile);\n  lsSet('fj_rekening',rekening);\n}",
    "Update save()"
)

# ── 3. Fix deleteTrx ─────────────────────────────────────────────
rep(
    "function deleteTrx(id){transactions=transactions.filter(t=>t.id!==id);save();renderTrx();updateAllStats();}",
    "function deleteTrx(id){transactions=transactions.filter(t=>t.id!==id);save();renderTrx();updateAllStats();if(GS_ON)gasPost({action:'deleteTrx',id}).catch(()=>{});}",
    "Fix deleteTrx sync"
)

# ── 4. Fix addDebt ───────────────────────────────────────────────
rep(
    "  toast('✅ Hutang ditambahkan!');\n}",
    "  toast('✅ Hutang ditambahkan!');\n  if(GS_ON)gasPost({action:'saveDebt',debt:d}).then(()=>setSync('ok','✅ Tersimpan di Sheets')).catch(()=>{});\n}",
    "Fix addDebt sync"
)

# ── 5. Fix deleteDebt ────────────────────────────────────────────
rep(
    "function deleteDebt(id){debts=debts.filter(d=>d.id!==id);save();renderDebts();updateDebtStats();updateNetWorth();}",
    "function deleteDebt(id){debts=debts.filter(d=>d.id!==id);save();renderDebts();updateDebtStats();updateNetWorth();if(GS_ON)gasPost({action:'deleteDebt',id}).catch(()=>{});}",
    "Fix deleteDebt sync"
)

# ── 6. Fix addGoal ───────────────────────────────────────────────
rep(
    "  toast('✅ Tujuan ditambahkan!');\n}",
    "  toast('✅ Tujuan ditambahkan!');\n  if(GS_ON)gasPost({action:'saveGoal',goal:g}).then(()=>setSync('ok','✅ Tersimpan di Sheets')).catch(()=>{});\n}",
    "Fix addGoal sync"
)

# ── 7. Fix deleteGoal ────────────────────────────────────────────
rep(
    "function deleteGoal(id){goals=goals.filter(g=>g.id!==id);save();renderGoals();renderDashGoals();}",
    "function deleteGoal(id){goals=goals.filter(g=>g.id!==id);save();renderGoals();renderDashGoals();if(GS_ON)gasPost({action:'deleteGoal',id}).catch(()=>{});}",
    "Fix deleteGoal sync"
)

# ── 8. Fix addAsset ──────────────────────────────────────────────
rep(
    "  toast('✅ Aset ditambahkan!');\n}",
    "  toast('✅ Aset ditambahkan!');\n  if(GS_ON)gasPost({action:'saveAsset',asset:a}).then(()=>setSync('ok','✅ Tersimpan di Sheets')).catch(()=>{});\n}",
    "Fix addAsset sync"
)

# ── 9. Fix deleteAsset ───────────────────────────────────────────
rep(
    "function deleteAsset(id){assets=assets.filter(a=>a.id!==id);save();renderAssets();updateNetWorth();setTimeout(drawAssetChart,100);}",
    "function deleteAsset(id){assets=assets.filter(a=>a.id!==id);save();renderAssets();updateNetWorth();setTimeout(drawAssetChart,100);if(GS_ON)gasPost({action:'deleteAsset',id}).catch(()=>{});}",
    "Fix deleteAsset sync"
)

# ── 10. Fix saveBudget ───────────────────────────────────────────
rep(
    "  toast('✅ Anggaran '+month+' disimpan!');\n",
    "  toast('✅ Anggaran '+month+' disimpan!');\n  if(GS_ON)gasPost({action:'saveBudget',month,data}).then(()=>setSync('ok','✅ Tersimpan di Sheets')).catch(()=>{});\n",
    "Fix saveBudget sync"
)

# ── 11. Rekening card di Dashboard ───────────────────────────────
rek_dash = """
    <!-- REKENING & E-WALLET -->
    <div class="card" style="margin-bottom:18px">
      <div class="fb" style="margin-bottom:12px">
        <div class="ct" style="margin-bottom:0">\U0001f4b3 Saldo Rekening & E-Wallet</div>
        <button class="btn bh" onclick="openRekeningModal()" style="font-size:11px;padding:5px 12px">✏️ Edit Saldo</button>
      </div>
      <div id="rek-dashboard"></div>
    </div>
"""
rep(
    '    <div class="g2" style="margin-bottom:16px">\n      <div class="card"><div class="ct">Arus Kas 6 Bulan</div>',
    rek_dash + '    <div class="g2" style="margin-bottom:16px">\n      <div class="card"><div class="ct">Arus Kas 6 Bulan</div>',
    "Rekening card di Dashboard"
)

# ── 12. Rekening strip di Transaksi ──────────────────────────────
rek_trx = """      <div class="card" style="margin-bottom:12px;padding:12px 16px">
        <div class="fb" style="margin-bottom:8px">
          <div style="font-size:11px;font-weight:700;color:var(--sub);text-transform:uppercase;letter-spacing:.08em">\U0001f4b3 Saldo Rekening</div>
          <button class="btn bh" onclick="openRekeningModal()" style="font-size:10px;padding:3px 10px">✏️ Edit</button>
        </div>
        <div id="rek-trx"></div>
      </div>
"""
rep(
    '  <div id="tab-trx" class="tab">\n    <div class="g2" style="margin-bottom:16px">',
    '  <div id="tab-trx" class="tab">\n' + rek_trx + '    <div class="g2" style="margin-bottom:16px">',
    "Rekening strip di Transaksi"
)

# ── 13. Rekening modal HTML ──────────────────────────────────────
rek_modal = """
<div id="rek-mo" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.75);z-index:999;align-items:center;justify-content:center;padding:16px">
  <div style="background:var(--surf);border:1px solid var(--bdr);border-radius:16px;padding:24px;width:100%;max-width:480px;max-height:90vh;overflow-y:auto">
    <div class="fb" style="margin-bottom:18px">
      <div style="font-size:16px;font-weight:700">\U0001f4b3 Edit Saldo Rekening & E-Wallet</div>
      <button class="bsm" onclick="closeRekeningModal()">✕</button>
    </div>
    <div style="font-size:10px;color:var(--sub);font-weight:700;letter-spacing:.1em;text-transform:uppercase;margin-bottom:12px">\U0001f3e6 Bank</div>
    <div class="fr fr2" style="margin-bottom:10px">
      <div class="fg"><label class="lb">BNI</label><input type="number" id="rek-BNI" placeholder="0" min="0"></div>
      <div class="fg"><label class="lb">JAGO</label><input type="number" id="rek-JAGO" placeholder="0" min="0"></div>
    </div>
    <div class="fr fr2" style="margin-bottom:10px">
      <div class="fg"><label class="lb">BRI</label><input type="number" id="rek-BRI" placeholder="0" min="0"></div>
      <div class="fg"><label class="lb">MANDIRI</label><input type="number" id="rek-MANDIRI" placeholder="0" min="0"></div>
    </div>
    <div class="fr fr2" style="margin-bottom:18px">
      <div class="fg"><label class="lb">BCA</label><input type="number" id="rek-BCA" placeholder="0" min="0"></div>
      <div class="fg"></div>
    </div>
    <div style="font-size:10px;color:var(--sub);font-weight:700;letter-spacing:.1em;text-transform:uppercase;margin-bottom:12px">\U0001f4f1 E-Wallet</div>
    <div class="fr fr2" style="margin-bottom:10px">
      <div class="fg"><label class="lb">DANA</label><input type="number" id="rek-DANA" placeholder="0" min="0"></div>
      <div class="fg"><label class="lb">GOPAY</label><input type="number" id="rek-GOPAY" placeholder="0" min="0"></div>
    </div>
    <div class="fr fr2" style="margin-bottom:22px">
      <div class="fg"><label class="lb">OVO</label><input type="number" id="rek-OVO" placeholder="0" min="0"></div>
      <div class="fg"><label class="lb">LINKAJA</label><input type="number" id="rek-LINKAJA" placeholder="0" min="0"></div>
    </div>
    <div class="fe">
      <button class="btn bh" onclick="closeRekeningModal()">Batal</button>
      <button class="btn bg" onclick="saveRekening()">\U0001f4be Simpan Saldo</button>
    </div>
  </div>
</div>
"""
rep('</body>', rek_modal + '</body>', "Rekening modal HTML")

# ── 14. Rekening JS functions ────────────────────────────────────
rek_js = """
// ══ REKENING & E-WALLET ═════════════════════════════════════════════
const REK_BANKS   = ['BNI','JAGO','BRI','MANDIRI','BCA'];
const REK_WALLETS = ['DANA','GOPAY','OVO','LINKAJA'];
const REK_ICON    = {BNI:'\U0001f7e0',JAGO:'\U0001f4d8',BRI:'\U0001f535',MANDIRI:'\U0001f7e1',BCA:'\U0001f537',DANA:'\U0001f4d8',GOPAY:'\U0001f7e2',OVO:'\U0001f7e3',LINKAJA:'\U0001f534'};
const REK_COLOR   = {BNI:'#f97316',JAGO:'#3b82f6',BRI:'#2563eb',MANDIRI:'#eab308',BCA:'#1e40af',DANA:'#1d4ed8',GOPAY:'#16a34a',OVO:'#7c3aed',LINKAJA:'#dc2626'};

function renderRekening() {
  const keys = [...REK_BANKS, ...REK_WALLETS];
  const totalBank   = REK_BANKS.reduce((s,k)=>s+(rekening[k]||0),0);
  const totalWallet = REK_WALLETS.reduce((s,k)=>s+(rekening[k]||0),0);
  const total       = totalBank + totalWallet;

  function makeCard(k) {
    return '<div style="background:var(--bg);border:1px solid var(--bdr);border-radius:10px;padding:10px 14px">'
      + '<div style="font-size:10px;color:var(--sub);font-weight:600;letter-spacing:.05em;margin-bottom:4px">'+REK_ICON[k]+' '+k+'</div>'
      + '<div style="font-family:var(--mono);font-size:13px;font-weight:700;color:'+REK_COLOR[k]+'">'+fmt(rekening[k]||0)+'</div>'
      + '</div>';
  }

  const dashHTML =
    '<div style="font-size:10px;color:var(--sub);font-weight:700;text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px">\U0001f3e6 Bank &nbsp;<span style=\\"float:right;color:var(--blue);font-family:var(--mono);font-size:11px\\">Total: '+fmt(totalBank)+'</span></div>'
    .replace(/\\\\/g,'')
    + '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:8px;margin-bottom:14px">'
    + REK_BANKS.map(makeCard).join('') + '</div>'
    + '<div style="font-size:10px;color:var(--sub);font-weight:700;text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px">\U0001f4f1 E-Wallet &nbsp;<span style=\\"float:right;color:var(--purple);font-family:var(--mono);font-size:11px\\">Total: '+fmt(totalWallet)+'</span></div>'
    .replace(/\\\\/g,'')
    + '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:8px;margin-bottom:12px">'
    + REK_WALLETS.map(makeCard).join('') + '</div>'
    + '<div style="border-top:1px solid var(--bdr);padding-top:10px;display:flex;justify-content:space-between;align-items:center">'
    + '<span style="font-size:12px;color:var(--sub)">Total Semua Rekening</span>'
    + '<span style="font-family:var(--mono);font-size:16px;font-weight:700;color:var(--grn)">'+fmt(total)+'</span></div>';

  const trxHTML = '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(100px,1fr));gap:6px">'
    + keys.map(k=>'<div style="display:flex;align-items:center;gap:6px">'
      + '<span>'+REK_ICON[k]+'</span>'
      + '<div><div style="font-size:9px;color:var(--sub);font-weight:600">'+k+'</div>'
      + '<div style="font-family:var(--mono);font-size:11px;font-weight:700;color:'+REK_COLOR[k]+'">'+fmt(rekening[k]||0)+'</div></div>'
      + '</div>').join('')
    + '</div>';

  if(document.getElementById('rek-dashboard')) document.getElementById('rek-dashboard').innerHTML = dashHTML;
  if(document.getElementById('rek-trx'))       document.getElementById('rek-trx').innerHTML = trxHTML;
}

function openRekeningModal() {
  [...REK_BANKS,...REK_WALLETS].forEach(k=>{const el=document.getElementById('rek-'+k);if(el)el.value=rekening[k]||0;});
  document.getElementById('rek-mo').style.display='flex';
}
function closeRekeningModal() { document.getElementById('rek-mo').style.display='none'; }
function saveRekening() {
  [...REK_BANKS,...REK_WALLETS].forEach(k=>{rekening[k]=parseFloat(document.getElementById('rek-'+k).value)||0;});
  lsSet('fj_rekening',rekening);
  closeRekeningModal();
  renderRekening();
  toast('✅ Saldo rekening disimpan!');
}
"""
rep('</script>\n</body>', rek_js + '\n</script>\n</body>', "Rekening JS functions")

# ── 15. Tambah renderRekening() di renderAll() ───────────────────
rep(
    "  safe(()=>{if($('tip-card'))$('tip-card').textContent=TIPS[new Date().getDate()%TIPS.length];},'tips');",
    "  safe(()=>{if($('tip-card'))$('tip-card').textContent=TIPS[new Date().getDate()%TIPS.length];},'tips');\n  safe(renderRekening,'rekening');",
    "Tambah renderRekening di renderAll"
)

with open(path, 'w', encoding='utf-8') as f:
    f.write(html)

print("\nSelesai! File sudah dimodifikasi.")
