# Acceptans: §55 (pilotens villkor) och §62 (färdigt system)

Kört 2026-10-30. Testerna finns i `tests/acceptance/test_fas7.py` och i de tidigare acceptanssviterna.
"Ja" betyder att ett test bevisar punkten och går igenom i CI. "Nej" betyder att punkten inte är uppfylld.
"Delvis" betyder att koden finns men att en grundare måste göra något.

## §55 Fas 7: kontrollerad pilot

| Villkor | Uppfyllt | Bevis |
|---|---|---|
| Alla tidigare kritiska tester är godkända | Ja | CI (`unittest` 3.11 och 3.12) är grönt på main; acceptanssviterna för Fas 1–6 ingår |
| Startbudget är uttryckligen fastställd | Ja | `test_55_2_start_budget_is_explicitly_set` (START_CAPITAL 500 kr visas i `pilot prepare`) |
| Behörigheter är begränsade | Ja | `test_55_3_permissions_are_limited_in_the_pilot` |
| Skyddad reserv är konfigurerad | Ja | `test_55_4_protected_reserve_is_configured` (MINIMUM_RESERVE 100 kr) |
| Nödstopp är testat | Ja | `test_55_5_kill_switch_blocks_agents_in_the_pilot`; i CI via `docs/KILL-SWITCH` (`test_kill_file_stops_agents_and_notifies_founders`) |
| Bokföring och loggning fungerar | Ja | `test_55_6_bookkeeping_and_logging_work` (riktig valuta i egen databas, revisionsloggen hel) |
| Mänskligt godkännande krävs där policyn föreskriver det | Ja | `test_55_7_human_approval_is_required` (kön, ingen agent kan godkänna, ingen import före godkännande) |
| Börja med en begränsad aktivitet | Ja | En produkt, manuell listning, inga förskottskostnader, stop-loss 50 kr |
| Ökad autonomi först efter dokumenterade resultat och granskning | Delvis | Oberoende granskning (D-055) är inte gjord än: `docs/reviews/REVIEW-PROMPT.md` |

## §62 Definition av färdigt system

| Punkt | Uppfyllt | Bevis |
|---|---|---|
| Agenterna har specialiserade roller | Ja | `test_fas2.py::test_agents_have_identifiable_roles` |
| Företaget har en fungerande hierarki | Ja | `test_fas3.py::test_work_flows_down_the_chain_to_the_worker_who_does_it` |
| Uppgifter fördelas och följs upp | Ja | `test_fas2.py::test_task_assigned_done_and_traceable` |
| Agenter kan resonera tillsammans inför beslut | Ja | `test_fas3.py::test_cfo_and_cro_disagree_is_escalated_with_documented_dispute`; 7c på Groq |
| Befogenheter kontrolleras tekniskt | Ja | `test_fas2.py::test_tool_outside_mandate_denied_and_logged` |
| Kapital och budgetar registreras korrekt | Ja | `test_fas4.py::test_overrun_is_blocked` |
| Nettovinst kan beräknas och verifieras | Ja | `test_fas4.py::test_net_profit_from_entries` |
| Riskgränser och reserver respekteras | Ja | `test_fas4.py::test_reserve_and_reserved_tax_are_never_spent` |
| Misstag dokumenteras och följs upp | Ja | `test_fas5.py::test_a_stop_becomes_an_incident_traced_to_the_event` |
| Lärdomar sparas beständigt | Ja | `test_fas5.py::test_lesson_has_sources_status_and_history` |
| Förbättringar testas innan de används i produktion | Ja | `test_fas5.py::test_unconfirmed_hypothesis_cannot_change_shared_rules`; utvecklaragentens vakt backar röd main |
| Agenter kan pausas och avvecklas kontrollerat | Ja | `test_fas2.py::test_suspended_agent_cannot_work` |
| Kritiska händelser kan granskas i efterhand | Ja | `test_fas3.py::test_from_decision_back_to_task_history_and_approvals` |
| Systemet följer lagar, avtal och plattformsvillkor | Nej | Kan inte testas i kod. Skattespåret väntar på Skatteverket (Q-TAX-01). Plattformens villkor och AI-regler kontrolleras av en grundare innan listning. |
| Utvecklingen följer kostnadspolicyn | Ja | `test_fas1.py::test_no_network_no_third_party_imports`; bara gratismodeller (D-008, D-050) |
| Yorgo och Robin kan utveckla vidare med gemensam dokumentation | Ja | Repot, DECISIONS.md, PROJECT_STATUS.md och `test_fas6.py::test_5_stop_and_restart_without_losing_critical_history` |

`Paragraph62.test_every_testable_item_has_an_existing_proof` kontrollerar att varje bevis i tabellen finns.

**Sammanfattning:** §55 har 8 av 9 villkor uppfyllda, och 1 är delvis uppfyllt (granskningen). §62 har 15 av 16 punkter uppfyllda; 1 kan inte testas (lagar och villkor).
