"""
legacy_mapping_dnd.py
---------------------
Interface drag-and-drop (HTML5) pour mapper des balises XML legacy vers des BT.
Affichée via streamlit.components.v1.html ; validation = navigation + st.query_params.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
from typing import Any

from convert_legacy import _parse_date as _legacy_parse_date


LEGACY_BT_BUCKETS = [
    ("📋 Facture & références", {"BT-1", "BT-2", "BT-3", "BT-5", "BT-9", "BT-10", "BT-12", "BT-13", "BT-22"}),
    ("🏢 Vendeur", {"BT-27", "BT-30", "BT-31", "BT-35", "BT-37", "BT-38", "BT-40", "BT-84", "BT-86"}),
    ("🏭 Acheteur", {"BT-44", "BT-47", "BT-48", "BT-50", "BT-53", "BT-54", "BT-55"}),
    ("📦 Lignes & TVA", {"BT-126", "BT-129", "BT-146", "BT-151", "BT-153"}),
]


def group_legacy_bt_entries(bt_entries: list[dict]) -> list[tuple[str, list[dict]]]:
    by_code = {x["bt"]: x for x in bt_entries}
    out: list[tuple[str, list[dict]]] = []
    seen: set[str] = set()
    for title, bset in LEGACY_BT_BUCKETS:
        chunk = [by_code[bt] for bt in sorted(bset) if bt in by_code]
        if chunk:
            out.append((title, chunk))
            seen |= {x["bt"] for x in chunk}
    rest = [by_code[bt] for bt in sorted(by_code.keys()) if bt not in seen]
    if rest:
        out.append(("Autres champs actifs", rest))
    return out


def _normalize_siren_bt(raw: str) -> str:
    d = re.sub(r"\D", "", raw or "")
    if len(d) == 14:
        return d[:9]
    return d


def _normalize_bt_value(bt: str, raw: str) -> str:
    raw = raw.strip()
    if bt in ("BT-2", "BT-9"):
        return _legacy_parse_date(raw)
    if bt in ("BT-30", "BT-47"):
        return _normalize_siren_bt(raw)
    return raw


def consume_legacy_dnd_query_params(uf: dict[str, str]) -> bool:
    """
    Si l'URL contient ?legacy_dnd=<base64url json {bt: tag}>, applique legacy_bt_overrides.
    Retourne True si consommé (st.rerun est appelé à l'intérieur).
    """
    import streamlit as st

    qp = st.query_params
    if "legacy_dnd" not in qp:
        return False
    raw = qp.get("legacy_dnd")
    if isinstance(raw, list):
        raw = raw[0]
    if not raw:
        return False
    try:
        pad = "=" * ((4 - len(raw) % 4) % 4)
        blob = base64.urlsafe_b64decode((raw + pad).encode("ascii"))
        data: dict[str, str] = json.loads(blob.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, binascii.Error, ValueError):
        try:
            del st.query_params["legacy_dnd"]
        except Exception:
            pass
        st.error("Paramètre de mapping invalide. Réessayez depuis l'interface.")
        return False

    base: dict[str, str] = dict(st.session_state.get("legacy_bt_overrides") or {})
    used_tags: list[str] = []
    for bt, tag in data.items():
        if not tag or str(tag).strip() == "":
            base.pop(str(bt), None)
            continue
        tag = str(tag).strip()
        bt = str(bt).strip()
        val = uf.get(tag, "").strip()
        if not val:
            continue
        base[bt] = _normalize_bt_value(bt, val)
        used_tags.append(tag)

    st.session_state.legacy_bt_overrides = base
    prev = list(st.session_state.get("legacy_tile_used") or [])
    st.session_state.legacy_tile_used = sorted(set(prev) | set(used_tags))

    try:
        del st.query_params["legacy_dnd"]
    except Exception:
        pass
    st.success("Mapping appliqué — le formulaire ci-dessous est à jour.")
    st.rerun()
    return True


def _json_for_html_script(obj: Any) -> str:
    """Sérialise en JSON sans casser le parseur ni fermer une balise </script> dans la page."""
    s = json.dumps(obj, ensure_ascii=False)
    return s.replace("<", "\\u003c")


def build_legacy_dnd_html(uf: dict[str, str], grouped: list[tuple[str, list[dict]]]) -> str:
    sources: list[dict[str, str]] = [{"tag": t, "value": v} for t, v in sorted(uf.items())]
    groups_js: list[dict[str, Any]] = []
    for title, chunk in grouped:
        groups_js.append(
            {
                "title": title,
                "targets": [{"bt": e["bt"], "label": e["label"]} for e in chunk],
            }
        )

    sources_json = _json_for_html_script(sources)
    groups_json = _json_for_html_script(groups_js)

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8"/>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; font-family: 'Segoe UI', system-ui, sans-serif;
    background: #f8fafc; color: #1e293b; font-size: 13px;
  }}
  .wrap {{
    display: flex; gap: 16px; min-height: 520px; padding: 12px;
  }}
  .col-left {{
    flex: 0 0 34%; max-width: 400px;
    background: #fff; border: 1px solid #e2e8f0; border-radius: 12px;
    padding: 12px; display: flex; flex-direction: column;
  }}
  .col-right {{
    flex: 1; min-width: 0;
    background: #fff; border: 1px solid #e2e8f0; border-radius: 12px;
    padding: 12px; overflow-y: auto; max-height: 680px;
  }}
  h3 {{ margin: 0 0 8px 0; font-size: 0.95rem; color: #0f172a; }}
  .hint {{ font-size: 0.78rem; color: #64748b; margin-bottom: 10px; line-height: 1.45; }}
  #pool {{
    flex: 1; display: flex; flex-direction: column; gap: 8px;
    min-height: 100px; padding: 8px; background: #f1f5f9; border-radius: 8px;
    border: 2px dashed #cbd5e1;
  }}
  .source-tile {{
    padding: 10px 12px; background: linear-gradient(160deg,#f8fafc,#fff);
    border: 1px solid #d7e3f0; border-radius: 10px; cursor: grab;
    box-shadow: 0 1px 2px rgba(0,60,120,0.06);
  }}
  .source-tile:active {{ cursor: grabbing; }}
  .tag {{ font-family: ui-monospace, Consolas, monospace; font-weight: 700; color: #005FAD; font-size: 0.82rem; word-break: break-all; }}
  .val {{ margin-top: 6px; color: #475569; font-size: 0.8rem; line-height: 1.35; max-height: 4.5em; overflow: hidden; }}
  .grp {{ margin-bottom: 14px; }}
  .grp-title {{ font-size: 0.8rem; font-weight: 700; color: #0f172a; margin-bottom: 8px; padding-bottom: 4px; border-bottom: 1px solid #e2e8f0; }}
  .slot-row {{ display: flex; flex-wrap: wrap; gap: 8px; }}
  .drop-slot {{
    flex: 1 1 220px; min-height: 78px; min-width: 170px;
    border: 2px dashed #86efac; background: #f0fdf4; border-radius: 10px;
    padding: 8px; transition: background .15s, border-color .15s;
  }}
  .drop-slot.dragover {{ background: #dcfce7; border-color: #16a34a; }}
  .slot-label {{ font-size: 0.72rem; font-weight: 600; color: #166534; margin-bottom: 4px; }}
  .slot-inner {{ min-height: 38px; }}
  .chip {{
    display: inline-flex; align-items: center; gap: 6px;
    background: #005FAD; color: #fff; padding: 4px 8px; border-radius: 8px;
    font-size: 0.78rem; font-family: ui-monospace, monospace; max-width: 100%;
  }}
  .chip button {{
    background: transparent; border: none; color: #fff; cursor: pointer;
    font-size: 1.1rem; line-height: 1; padding: 0 2px; opacity: 0.9;
  }}
  .chip button:hover {{ opacity: 1; }}
  .actions {{ margin-top: 14px; display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }}
  .btn {{
    background: linear-gradient(135deg,#005FAD,#0077CC); color: #fff; border: none;
    border-radius: 8px; padding: 10px 18px; font-weight: 600; cursor: pointer; font-size: 0.88rem;
  }}
  .btn-secondary {{ background: #64748b; }}
  .bin {{
    margin-top: 8px; padding: 10px; text-align: center; border: 2px dashed #f87171;
    background: #fef2f2; border-radius: 8px; color: #991b1b; font-size: 0.8rem;
  }}
  .bin.dragover {{ background: #fee2e2; border-color: #dc2626; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="col-left">
    <h3>Balises à mapper</h3>
    <p class="hint">Glissez une tuile vers un champ BT à droite. × sur la puce ou corbeille pour libérer la balise.</p>
    <div id="pool"></div>
    <div id="bin" class="bin">Corbeille — déposer ici pour retirer une affectation</div>
  </div>
  <div class="col-right">
    <h3>Champs cibles (BT)</h3>
    <p class="hint">Une balise par champ. Vous pouvez déplacer une puce d'un champ à l'autre.</p>
    <div id="targets"></div>
    <div class="actions">
      <button type="button" class="btn" onclick="submitMapping()">Valider le mapping</button>
      <button type="button" class="btn btn-secondary" onclick="resetAll()">Tout effacer</button>
    </div>
  </div>
</div>
<script type="application/json" id="legacy-dnd-sources">{sources_json}</script>
<script type="application/json" id="legacy-dnd-groups">{groups_json}</script>
<script>
const SOURCES = JSON.parse(document.getElementById('legacy-dnd-sources').textContent);
const GROUPS = JSON.parse(document.getElementById('legacy-dnd-groups').textContent);
let assignments = {{}};

function allowDrop(ev) {{ ev.preventDefault(); }}

function dragStartTag(ev, tag) {{
  ev.dataTransfer.setData('application/x-tag', tag);
  ev.dataTransfer.setData('text/plain', tag);
  ev.dataTransfer.effectAllowed = 'move';
}}

function dragStartChip(ev, tag, fromBt) {{
  ev.dataTransfer.setData('application/x-tag', tag);
  ev.dataTransfer.setData('text/plain', tag);
  ev.dataTransfer.setData('application/x-from-bt', fromBt);
  ev.stopPropagation();
}}

function assignedTags() {{
  const s = new Set();
  Object.values(assignments).forEach(t => {{ if (t) s.add(t); }});
  return s;
}}

function renderPool() {{
  const pool = document.getElementById('pool');
  pool.innerHTML = '';
  const used = assignedTags();
  let any = false;
  SOURCES.forEach(s => {{
    if (used.has(s.tag)) return;
    any = true;
    const el = document.createElement('div');
    el.className = 'source-tile';
    el.draggable = true;
    el.ondragstart = (e) => dragStartTag(e, s.tag);
    const t1 = document.createElement('div');
    t1.className = 'tag';
    t1.textContent = s.tag;
    const t2 = document.createElement('div');
    t2.className = 'val';
    const v = s.value || '';
    t2.textContent = v.length > 140 ? v.slice(0, 140) + '…' : v;
    el.appendChild(t1);
    el.appendChild(t2);
    pool.appendChild(el);
  }});
  if (!any) {{
    const p = document.createElement('p');
    p.className = 'hint';
    p.style.margin = '0';
    p.textContent = "Toutes les balises sont affectées à droite — utilisez × ou la corbeille pour les ramener ici.";
    pool.appendChild(p);
  }}
}}

function assignToBt(bt, tag) {{
  if (!tag) return;
  Object.keys(assignments).forEach(b => {{ if (assignments[b] === tag) delete assignments[b]; }});
  assignments[bt] = tag;
  renderPool();
  renderTargets();
}}

function renderTargets() {{
  const root = document.getElementById('targets');
  root.innerHTML = '';
  GROUPS.forEach(g => {{
    const grp = document.createElement('div');
    grp.className = 'grp';
    const gt = document.createElement('div');
    gt.className = 'grp-title';
    gt.textContent = g.title;
    grp.appendChild(gt);
    const row = document.createElement('div');
    row.className = 'slot-row';
    g.targets.forEach(t => {{
      const slot = document.createElement('div');
      slot.className = 'drop-slot';
      slot.ondragover = (e) => {{ e.preventDefault(); slot.classList.add('dragover'); }};
      slot.ondragleave = () => slot.classList.remove('dragover');
      slot.ondrop = (e) => {{
        e.preventDefault();
        slot.classList.remove('dragover');
        const tag = e.dataTransfer.getData('application/x-tag') || e.dataTransfer.getData('text/plain');
        if (!tag) return;
        assignToBt(t.bt, tag);
      }};
      const lbl = document.createElement('div');
      lbl.className = 'slot-label';
      lbl.textContent = t.bt + ' — ' + t.label;
      const inner = document.createElement('div');
      inner.className = 'slot-inner';
      const tag = assignments[t.bt];
      if (!tag) {{
        const hint = document.createElement('span');
        hint.className = 'hint';
        hint.style.opacity = '0.65';
        hint.textContent = 'Déposer ici';
        inner.appendChild(hint);
      }} else {{
        const chip = document.createElement('span');
        chip.className = 'chip';
        chip.draggable = true;
        chip.ondragstart = (ev) => dragStartChip(ev, tag, t.bt);
        chip.appendChild(document.createTextNode(tag + ' '));
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.setAttribute('aria-label', 'Retirer');
        btn.textContent = '×';
        btn.onclick = () => {{ delete assignments[t.bt]; renderPool(); renderTargets(); }};
        chip.appendChild(btn);
        inner.appendChild(chip);
      }}
      slot.appendChild(lbl);
      slot.appendChild(inner);
      row.appendChild(slot);
    }});
    grp.appendChild(row);
    root.appendChild(grp);
  }});
}}

function resetAll() {{
  assignments = {{}};
  renderPool();
  renderTargets();
}}

(function setupBin() {{
  const bin = document.getElementById('bin');
  bin.ondragover = (e) => {{ e.preventDefault(); bin.classList.add('dragover'); }};
  bin.ondragleave = () => bin.classList.remove('dragover');
  bin.ondrop = (e) => {{
    e.preventDefault();
    bin.classList.remove('dragover');
    const tag = e.dataTransfer.getData('application/x-tag') || e.dataTransfer.getData('text/plain');
    const fromBt = e.dataTransfer.getData('application/x-from-bt');
    if (fromBt && assignments[fromBt] === tag) delete assignments[fromBt];
    else {{
      Object.keys(assignments).forEach(b => {{ if (assignments[b] === tag) delete assignments[b]; }});
    }}
    renderPool();
    renderTargets();
  }};
}})();

function b64UrlEncodeUtf8(str) {{
  const b64 = btoa(unescape(encodeURIComponent(str)));
  return b64.replace(/\\+/g, '-').replace(/\\//g, '_').replace(/=+$/, '');
}}

function submitMapping() {{
  const j = JSON.stringify(assignments);
  const b64 = b64UrlEncodeUtf8(j);
  const u = new URL(window.top.location.href);
  u.searchParams.set('legacy_dnd', b64);
  window.top.location.href = u.toString();
}}

renderPool();
renderTargets();
</script>
</body>
</html>"""


def render_legacy_dnd_component(uf: dict[str, str], grouped: list[tuple[str, list[dict]]], height: int = 740) -> None:
    import streamlit.components.v1 as components

    html_doc = build_legacy_dnd_html(uf, grouped)
    components.html(html_doc, height=height, scrolling=True)
