"""Moteur d'évaluation des 4 règles d'usage des buques Clun'ss."""

from __future__ import annotations

import math
import re
from typing import Any

from .bdd_loader import BddIndex, BddRecord
from .phonetics import (
    PhoneticProfile,
    build_profile,
    compare_profiles,
    is_match,
    normalize_visual,
    phonetize_fr,
)


COLOR_LABELS = {
    "violet": "Règle 2 : CT",
    "rouge": "Règle 1 : < 10 ans",
    "orange": "Règle 4 : Problématique",
    "jaune": "Règle 3 : Même prom'ss",
    "vert": "Utilisable",
    "empty": "Non renseigné",
}


def _char_mask(s: str) -> int:
    m = 0
    for ch in s:
        o = ord(ch)
        m |= 1 << (o if o < 128 else 127)
    return m


def _deletes_1(s: str) -> list[str]:
    if len(s) <= 1:
        return []
    return [s[:i] + s[i + 1 :] for i in range(len(s))]


class _FastProfileIndex:
    """
    Index hybride exact + SymSpell (distance <= 1) + filtre binaire par masque de caractères.
    Garantit 100% des correspondances exactes et approchées sans balayage O(N*M) complet.
    """

    def __init__(self, items: list[tuple[PhoneticProfile, Any]]) -> None:
        # Regrouper les payloads par PhoneticProfile unique
        self.profiles: list[PhoneticProfile] = []
        self.payloads: list[list[Any]] = []
        prof_to_idx: dict[PhoneticProfile, int] = {}

        for prof, payload in items:
            idx = prof_to_idx.get(prof)
            if idx is None:
                idx = len(self.profiles)
                prof_to_idx[prof] = idx
                self.profiles.append(prof)
                self.payloads.append([payload])
            else:
                self.payloads[idx].append(payload)

        self.exact_map: dict[str, set[int]] = {}
        self.del1_map: dict[str, set[int]] = {}
        self.prefix5_map: dict[str, set[int]] = {}
        self.prof_max_len: list[int] = []
        self.prof_masks: list[tuple[list[tuple[str, int, int]], list[tuple[str, int, int]]]] = []

        for idx, prof in enumerate(self.profiles):
            v_info: list[tuple[str, int, int]] = []
            p_info: list[tuple[str, int, int]] = []
            max_l = 0

            all_strs = list(prof.visual_readings) + list(prof.phonetic_readings)
            for s in prof.visual_readings:
                if s:
                    l = len(s)
                    max_l = max(max_l, l)
                    v_info.append((s, l, _char_mask(s)))
            for s in prof.phonetic_readings:
                if s:
                    l = len(s)
                    max_l = max(max_l, l)
                    p_info.append((s, l, _char_mask(s)))

            self.prof_max_len.append(max_l)
            self.prof_masks.append((v_info, p_info))

            for s in all_strs:
                if not s:
                    continue
                self.exact_map.setdefault(s, set()).add(idx)
                if len(s) >= 5:
                    self.prefix5_map.setdefault(s[:5], set()).add(idx)
                if len(s) >= 4:
                    for d in _deletes_1(s):
                        self.del1_map.setdefault(d, set()).add(idx)

    def query_candidates(
        self,
        prof: PhoneticProfile,
        threshold: float,
        include_prefix: bool = False,
    ) -> set[int]:
        candidates: set[int] = set()
        q_strs = [s for s in (list(prof.visual_readings) + list(prof.phonetic_readings)) if s]
        if not q_strs:
            return candidates

        # 1) Correspondances exactes et distance <= 1 (O(L))
        for s in q_strs:
            if s in self.exact_map:
                candidates.update(self.exact_map[s])
            if len(s) >= 4:
                if s in self.del1_map:
                    candidates.update(self.del1_map[s])
                for d in _deletes_1(s):
                    if d in self.exact_map:
                        candidates.update(self.exact_map[d])
                    if d in self.del1_map:
                        candidates.update(self.del1_map[d])

        # 2) Préfixes pour Règle 3 (ex: Polar vs Polaris)
        if include_prefix:
            for s in q_strs:
                if len(s) >= 5 and s[:5] in self.prefix5_map:
                    candidates.update(self.prefix5_map[s[:5]])

        # 3) Cas distance >= 2 : uniquement si la longueur maximale permet dist >= 2 au seuil donné
        if threshold < 0.999:
            min_len_dist2 = max(4, math.ceil(2.0 / max(0.01, 1.0 - threshold)))
            q_max_len = max(len(s) for s in q_strs)
            if q_max_len >= int(min_len_dist2 * threshold) - 1:
                qv_masks = [(len(s), _char_mask(s)) for s in prof.visual_readings if len(s) >= 4]
                qp_masks = [(len(s), _char_mask(s)) for s in prof.phonetic_readings if len(s) >= 4]
                for idx, max_l in enumerate(self.prof_max_len):
                    if max_l < min_len_dist2 and q_max_len < min_len_dist2:
                        continue
                    if idx in candidates:
                        continue
                    v_info, p_info = self.prof_masks[idx]
                    possible = False
                    for ql, qm in qv_masks:
                        for _, rl, rm in v_info:
                            mx = ql if ql > rl else rl
                            md = int(mx * (1.0 - threshold) + 1e-9)
                            if abs(ql - rl) <= md and (qm & ~rm).bit_count() <= md and (rm & ~qm).bit_count() <= md:
                                possible = True
                                break
                        if possible:
                            break
                    if not possible:
                        for ql, qm in qp_masks:
                            for _, rl, rm in p_info:
                                mx = ql if ql > rl else rl
                                md = int(mx * (1.0 - threshold) + 1e-9)
                                if abs(ql - rl) <= md and (qm & ~rm).bit_count() <= md and (rm & ~qm).bit_count() <= md:
                                    possible = True
                                    break
                            if possible:
                                break
                    if possible:
                        candidates.add(idx)

        return candidates


def _check_problematic(
    profile: PhoneticProfile,
    terms: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Détecte automatiquement les correspondances avec le lexique de la règle 4."""
    if not profile.raw:
        return []

    matches: list[dict[str, Any]] = []
    visual_tokens: set[str] = set()
    phonetic_tokens: set[str] = set()
    for reading in profile.expanded_readings:
        for tok in re.split(r"[^a-zA-ZÀ-ÿ0-9]+", reading):
            nv = normalize_visual(tok)
            if nv:
                visual_tokens.add(nv)
                for ph in phonetize_fr(tok):
                    if ph:
                        phonetic_tokens.add(ph)

    q_masks = [_char_mask(v) for v in profile.visual_readings if v]
    q_max = max((len(v) for v in profile.visual_readings if v), default=0)

    for item in terms:
        raw_term = item["term"]
        term_prof = build_profile(raw_term)
        t_vis = term_prof.visual_clean
        t_ph = term_prof.primary_phonetic
        if not t_vis:
            continue

        matched = False
        match_reason = ""

        if len(t_vis) >= 5:
            if any(t_vis in v for v in profile.visual_readings if v):
                matched = True
                match_reason = f"Contient « {raw_term} » (orthographe)"
            elif t_ph and any(t_ph in ph for ph in profile.phonetic_readings if ph):
                matched = True
                match_reason = f"Contient « {raw_term} » (phonétique)"
            elif abs(q_max - len(t_vis)) <= max(1, int(max(q_max, len(t_vis)) * 0.15)):
                tm = _char_mask(t_vis)
                if any((qm & ~tm).bit_count() <= 2 and (tm & ~qm).bit_count() <= 2 for qm in q_masks):
                    best, _, _ = compare_profiles(profile, term_prof, min_threshold=0.88)
                    if best >= 0.88:
                        matched = True
                        match_reason = f"Proche de « {raw_term} » ({round(best * 100)}%)"
        else:
            if t_vis in visual_tokens or t_vis in profile.visual_readings:
                matched = True
                match_reason = f"Mot « {raw_term} » détecté"
            elif t_ph and (t_ph in phonetic_tokens or t_ph in profile.phonetic_readings):
                matched = True
                match_reason = f"Son proche du mot « {raw_term} »"

        if matched:
            matches.append(
                {
                    "term": raw_term,
                    "category": item.get("category", "Personnalisé"),
                    "notes": item.get("notes", ""),
                    "reason": match_reason,
                    "manual": False,
                }
            )

    return matches


def _match_bdd_records(
    prof: PhoneticProfile,
    index: _FastProfileIndex,
    threshold: float,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """Recherche rapide des correspondances dans un index BDD."""
    if not prof.raw:
        return []

    cand_ids = index.query_candidates(prof, threshold=threshold, include_prefix=False)
    hits: list[tuple[float, float, float, BddRecord]] = []
    for idx in cand_ids:
        ref_prof = index.profiles[idx]
        matched, best, ortho, phon = is_match(prof, ref_prof, threshold, mode="r12")
        if matched:
            for rec in index.payloads[idx]:
                hits.append((best, ortho, phon, rec))

    hits.sort(key=lambda x: (-x[0], -(x[3].proms or 0), x[3].buque.lower()))
    out = []
    for best, ortho, phon, rec in hits[:limit]:
        out.append(
            {
                "buque": rec.buque,
                "nom": rec.nom,
                "prenom": rec.prenom,
                "fams": rec.fams,
                "proms": rec.proms,
                "annee": rec.annee,
                "source": rec.source,
                "score": round(best * 100),
                "ortho_score": round(ortho * 100),
                "phon_score": round(phon * 100),
            }
        )
    return out


def _build_exact_maps(
    records: list[BddRecord],
) -> tuple[dict[str, list[BddRecord]], dict[str, list[BddRecord]]]:
    by_visual: dict[str, list[BddRecord]] = {}
    by_phonetic: dict[str, list[BddRecord]] = {}
    for rec in records:
        for v in rec.profile.visual_readings:
            if v:
                by_visual.setdefault(v, []).append(rec)
        for ph in rec.profile.phonetic_readings:
            if ph:
                by_phonetic.setdefault(ph, []).append(rec)
    return by_visual, by_phonetic


def _match_older_pgs_exact(
    prof: PhoneticProfile,
    by_visual: dict[str, list[BddRecord]],
    by_phonetic: dict[str, list[BddRecord]],
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Trouve les PGs > 10 ans exacts (orthographe ou phonétique) à titre informatif."""
    if not prof.raw:
        return []
    seen_keys: set[tuple[str, int | None, str]] = set()
    hits: list[dict[str, Any]] = []

    def _collect(rec: BddRecord, ortho: int, phon: int) -> None:
        key = (rec.buque, rec.proms, rec.nom)
        if key in seen_keys:
            return
        seen_keys.add(key)
        hits.append(
            {
                "buque": rec.buque,
                "nom": rec.nom,
                "prenom": rec.prenom,
                "fams": rec.fams,
                "proms": rec.proms,
                "source": rec.source,
                "score": max(ortho, phon),
                "ortho_score": ortho,
                "phon_score": phon,
            }
        )

    for v in prof.visual_readings:
        for rec in by_visual.get(v, []):
            _collect(rec, 100, 100 if rec.profile.primary_phonetic in prof.phonetic_readings else 90)
    for ph in prof.phonetic_readings:
        for rec in by_phonetic.get(ph, []):
            _collect(rec, 100 if rec.profile.visual_clean in prof.visual_readings else 85, 100)

    hits.sort(key=lambda x: (-(x["proms"] or 0), -x["score"]))
    return hits[:limit]


def _determine_color(active_rules: list[int], is_empty: bool) -> str:
    if is_empty:
        return "empty"
    if 2 in active_rules:
        return "violet"
    if 1 in active_rules:
        return "rouge"
    if 4 in active_rules:
        return "orange"
    if 3 in active_rules:
        return "jaune"
    return "vert"


def evaluate_all(
    entries: list[dict[str, Any]],
    bdd: BddIndex,
    settings: dict[str, Any],
    overrides_map: dict[tuple[int, int], dict[str, Any]],
    problematic_terms: list[dict[str, Any]],
) -> dict[str, Any]:
    """Évalue toutes les feuilles saisies selon les 4 règles et génère les stats."""
    current_proms = int(settings["current_proms"])
    rule1_years = int(settings["rule1_years"])
    threshold_r12 = float(settings["threshold_r12"])
    threshold_r3 = float(settings["threshold_r3"])
    r3_scope = settings.get("r3_scope", "all")

    start_proms = current_proms - rule1_years
    recent_pgs = bdd.get_pgs_in_window(current_proms, rule1_years)
    older_pgs = [
        r for r in bdd.pg_records if r.proms is None or r.proms < start_proms
    ]

    recent_index = _FastProfileIndex([(r.profile, r) for r in recent_pgs])
    ct_index = _FastProfileIndex([(r.profile, r) for r in bdd.ct_records])
    older_by_visual, older_by_phonetic = _build_exact_maps(older_pgs)

    # Pré-calculer les profils des choix de la prom'ss en cours pour Règle 3
    choices_by_entry: dict[int, dict[int, tuple[str, str, PhoneticProfile]]] = {}
    r3_items: list[tuple[PhoneticProfile, tuple[int, str, int, str]]] = []
    for entry in entries:
        eid = entry["id"]
        nom = entry["nom"]
        for idx in (1, 2, 3):
            raw = (entry.get(f"choix{idx}") or "").strip()
            police = (entry.get(f"police{idx}") or "").strip()
            prof = build_profile(raw)
            choices_by_entry.setdefault(eid, {})[idx] = (raw, police, prof)
            if raw and (r3_scope != "choice1" or idx == 1):
                r3_items.append((prof, (eid, nom, idx, raw)))

    r3_index = _FastProfileIndex(r3_items)

    summary = {
        "total_students": len(entries),
        "total_choices": 0,
        "vert": 0,
        "rouge": 0,
        "violet": 0,
        "jaune": 0,
        "orange": 0,
        "empty": 0,
        "students_without_green": 0,
    }

    rows_out: list[dict[str, Any]] = []

    for entry in entries:
        eid = entry["id"]
        row_choices: list[dict[str, Any]] = []
        has_green = False

        for idx in (1, 2, 3):
            raw, police, prof = choices_by_entry[eid][idx]
            override = overrides_map.get(
                (eid, idx),
                {
                    "is_problematic": 0,
                    "problematic_reason": "",
                    "ignored_rules": [],
                },
            )
            ignored_rules = set(override.get("ignored_rules", []))

            if not raw:
                summary["empty"] += 1
                row_choices.append(
                    {
                        "choice_index": idx,
                        "raw": "",
                        "police": police,
                        "color": "empty",
                        "label": COLOR_LABELS["empty"],
                        "active_rules": [],
                        "ignored_rules": sorted(ignored_rules),
                        "override": override,
                        "phonetic": prof.to_dict(),
                        "conflicts": {"r1": [], "r2": [], "r3": [], "r4": [], "older_pgs": []},
                    }
                )
                continue

            summary["total_choices"] += 1

            r1_matches = _match_bdd_records(prof, recent_index, threshold_r12)
            r2_matches = _match_bdd_records(prof, ct_index, threshold_r12)
            older_matches = _match_older_pgs_exact(
                prof, older_by_visual, older_by_phonetic
            )

            # Règle 3 : Ressemblance dans la même prom'ss (autres étudiants uniquement)
            r3_matches: list[dict[str, Any]] = []
            r3_cands = r3_index.query_candidates(prof, threshold=threshold_r3, include_prefix=True)
            for cand_idx in r3_cands:
                other_prof = r3_index.profiles[cand_idx]
                matched, best, ortho, phon = is_match(
                    prof, other_prof, threshold_r3, mode="r3"
                )
                if not matched:
                    continue
                for other_eid, other_nom, other_idx, other_raw in r3_index.payloads[cand_idx]:
                    if other_eid == eid:
                        continue
                    r3_matches.append(
                        {
                            "entry_id": other_eid,
                            "nom": other_nom,
                            "choice_index": other_idx,
                            "buque": other_raw,
                            "score": round(best * 100),
                            "ortho_score": round(ortho * 100),
                            "phon_score": round(phon * 100),
                        }
                    )
            r3_matches.sort(key=lambda x: (-x["score"], x["nom"].lower(), x["choice_index"]))

            # Règle 4 : Références problématiques (auto + surcharge manuelle)
            r4_auto = _check_problematic(prof, problematic_terms)
            r4_matches: list[dict[str, Any]] = []
            is_prob_flag = int(override.get("is_problematic", 0))
            if is_prob_flag == 1:
                r4_matches.append(
                    {
                        "term": raw,
                        "category": "Signalement manuel",
                        "reason": override.get("problematic_reason")
                        or "Signalé manuellement comme référence problématique",
                        "manual": True,
                    }
                )
                r4_matches.extend(r4_auto)
            elif is_prob_flag == 0:
                r4_matches.extend(r4_auto)

            raw_rules = []
            if r1_matches:
                raw_rules.append(1)
            if r2_matches:
                raw_rules.append(2)
            if r3_matches:
                raw_rules.append(3)
            if r4_matches:
                raw_rules.append(4)

            active_rules = [r for r in raw_rules if r not in ignored_rules]
            color = _determine_color(active_rules, is_empty=False)
            summary[color] += 1
            if color == "vert":
                has_green = True

            row_choices.append(
                {
                    "choice_index": idx,
                    "raw": raw,
                    "police": police,
                    "color": color,
                    "label": COLOR_LABELS[color],
                    "active_rules": active_rules,
                    "all_triggered_rules": raw_rules,
                    "ignored_rules": sorted(ignored_rules),
                    "override": override,
                    "phonetic": prof.to_dict(),
                    "conflicts": {
                        "r1": r1_matches,
                        "r2": r2_matches,
                        "r3": r3_matches,
                        "r4": r4_matches,
                        "older_pgs": older_matches,
                    },
                }
            )

        if not has_green and any(c["raw"] for c in row_choices):
            summary["students_without_green"] += 1

        rows_out.append(
            {
                "id": eid,
                "nom": entry["nom"],
                "prenom": entry.get("prenom", ""),
                "created_by": entry.get("created_by", ""),
                "updated_by": entry.get("updated_by", ""),
                "has_green": has_green,
                "choices": row_choices,
            }
        )

    return {
        "settings": settings,
        "summary": summary,
        "rows": rows_out,
    }


def evaluate_single_buque(
    raw_text: str,
    entries: list[dict[str, Any]],
    bdd: BddIndex,
    settings: dict[str, Any],
    problematic_terms: list[dict[str, Any]],
    ignore_entry_id: int | None = None,
) -> dict[str, Any]:
    """Teste une buque isolée contre toutes les règles (pour le Testeur phonétique)."""
    raw = (raw_text or "").strip()
    prof = build_profile(raw)
    if not raw:
        return {
            "raw": "",
            "color": "empty",
            "label": COLOR_LABELS["empty"],
            "active_rules": [],
            "phonetic": prof.to_dict(),
            "conflicts": {"r1": [], "r2": [], "r3": [], "r4": [], "older_pgs": []},
        }

    current_proms = int(settings["current_proms"])
    rule1_years = int(settings["rule1_years"])
    threshold_r12 = float(settings["threshold_r12"])
    threshold_r3 = float(settings["threshold_r3"])
    start_proms = current_proms - rule1_years

    recent_pgs = bdd.get_pgs_in_window(current_proms, rule1_years)
    older_pgs = [
        r for r in bdd.pg_records if r.proms is None or r.proms < start_proms
    ]

    recent_index = _FastProfileIndex([(r.profile, r) for r in recent_pgs])
    ct_index = _FastProfileIndex([(r.profile, r) for r in bdd.ct_records])
    older_by_visual, older_by_phonetic = _build_exact_maps(older_pgs)

    r1_matches = _match_bdd_records(prof, recent_index, threshold_r12)
    r2_matches = _match_bdd_records(prof, ct_index, threshold_r12)
    older_matches = _match_older_pgs_exact(prof, older_by_visual, older_by_phonetic)

    r3_matches: list[dict[str, Any]] = []
    for entry in entries:
        if ignore_entry_id is not None and entry["id"] == ignore_entry_id:
            continue
        for idx in (1, 2, 3):
            other_raw = (entry.get(f"choix{idx}") or "").strip()
            if not other_raw:
                continue
            other_prof = build_profile(other_raw)
            matched, best, ortho, phon = is_match(prof, other_prof, threshold_r3, mode="r3")
            if matched:
                r3_matches.append(
                    {
                        "entry_id": entry["id"],
                        "nom": entry["nom"],
                        "choice_index": idx,
                        "buque": other_raw,
                        "score": round(best * 100),
                        "ortho_score": round(ortho * 100),
                        "phon_score": round(phon * 100),
                    }
                )
    r3_matches.sort(key=lambda x: (-x["score"], x["nom"].lower()))

    r4_matches = _check_problematic(prof, problematic_terms)

    active_rules = []
    if r1_matches:
        active_rules.append(1)
    if r2_matches:
        active_rules.append(2)
    if r3_matches:
        active_rules.append(3)
    if r4_matches:
        active_rules.append(4)

    color = _determine_color(active_rules, is_empty=False)
    return {
        "raw": raw,
        "color": color,
        "label": COLOR_LABELS[color],
        "active_rules": active_rules,
        "phonetic": prof.to_dict(),
        "conflicts": {
            "r1": r1_matches,
            "r2": r2_matches,
            "r3": r3_matches,
            "r4": r4_matches,
            "older_pgs": older_matches,
        },
    }
