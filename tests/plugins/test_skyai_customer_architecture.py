from __future__ import annotations

import ast
import json
from pathlib import Path

from plugins.skyai_customer import dev_gateway, public_tools


ARCHITECTURE_PATH = Path("plugins/skyai_customer/ARCHITECTURE.md")
QA_PRINCIPLES_PATH = Path("plugins/skyai_customer/fixtures/qa_behavior_principles.json")
COMPARE_SCENARIOS_PATH = Path("plugins/skyai_customer/fixtures/compare_scenarios.json")


def test_architecture_contract_declares_hermes_led_reasoning() -> None:
    text = ARCHITECTURE_PATH.read_text(encoding="utf-8")
    compact = " ".join(text.split())

    assert "Hermes reasons" in text
    assert "The SkyAI backend and tools provide public facts" in text
    assert "Do not reintroduce keyword routers" in text
    assert "only canonical source" in compact
    assert "historical v1/clean-room archive" in compact
    assert "Keyword classifiers, synthetic response templates" in compact
    assert "wire compatibility only" in compact
    assert "Plugin vs Fork" in text
    assert "Three-Hour Upstream Hermes Update Flow" in text
    assert "must not auto-merge or deploy" in compact


def test_skyai_prompt_is_principle_based_not_script_pack() -> None:
    prompt = dev_gateway.build_skyai_system_prompt()

    assert "Hermes мисли" in prompt
    assert "не е заповед какво да кажеш" in prompt
    assert len(prompt) < 7100
    assert "SkyAI sales playbook" not in prompt
    assert "do_not_say" not in prompt
    assert "customer_facing_flow" not in prompt
    assert "tone_anchors" not in prompt


def test_skyai_prompt_treats_prior_turns_as_shared_context() -> None:
    prompt = dev_gateway.build_skyai_system_prompt()
    architecture = " ".join(ARCHITECTURE_PATH.read_text(encoding="utf-8").split())

    assert "Историята е общ контекст" in prompt
    assert "Отговаряй само с новото" in prompt
    assert "сравни всяко твърдение и стъпка" in prompt
    assert "ако смисълът вече е даден, изтрий го" in prompt
    assert "последната реплика" in prompt
    assert "Полезността или свързаността не оправдава повторение" in prompt
    assert "поправка/недоволство" in prompt
    assert "поправи само новото" in prompt
    assert "изрично искане или корекция" in prompt
    assert "само нужната част" in prompt
    assert "Conversation history is shared reasoning context" in architecture
    assert "prior information is" in architecture
    assert "presumed known" in architecture
    assert "delta in the latest" in architecture
    assert "summarizing the old answer" in architecture
    assert "compare every claim and next step in its draft" in architecture
    assert "Usefulness or relevance does not justify" in architecture
    assert "prompt-and-evaluation principle" in architecture
    assert "backend deduplication" in architecture
    assert "keyword rule" in architecture


def test_campaign_gift_validity_precedes_transfer_reasoning() -> None:
    prompt = dev_gateway.build_skyai_system_prompt()

    assert "не извеждай едната дата от другата" in prompt
    assert "историческите условия на конкретната кампания" in prompt
    assert "отделно от ползването на основния ваучер" in prompt
    assert "„Неизползван“ не означава „използваем сега“" in prompt
    assert "само че изтичане е възможно и е нужна проверка" in prompt
    assert "не обявявай подаръка за изтекъл" in prompt
    assert "не предлагай прехвърляне, ръчно изключение или ескалация" in prompt
    assert prompt.index(
        "точната дата на покупката или създаването на entitlement"
    ) < prompt.index(
        "собственост, профил или прехвърляне"
    )


def test_campaign_gift_validity_is_general_evaluation_material() -> None:
    principles = json.loads(QA_PRINCIPLES_PATH.read_text(encoding="utf-8"))
    scenarios = json.loads(COMPARE_SCENARIOS_PATH.read_text(encoding="utf-8"))

    principle = next(
        case for case in principles if case["id"] == "campaign_gift_time_validity"
    )
    assert principle["source_threads"] == ["generalized_campaign_validity_regression"]
    assert "received or gifted" in principle["principle"]
    assert "purchase or entitlement-creation date" in principle["principle"]
    assert "historical campaign terms" in principle["principle"]
    assert "separate from main-voucher use" in principle["principle"]
    assert "Unused is not the same as currently usable" in principle["principle"]
    assert "expiry is possible" in principle["principle"]
    assert "never declare expiry as fact" in principle["principle"]
    assert "before transfer or exception guidance" in principle["principle"]

    scenario = next(
        case for case in scenarios if case["id"] == "campaign_gift_time_validity"
    )
    assert scenario["history"] == [
        {
            "role": "user",
            "content": (
                "Получих основния ваучер като подарък преди няколко години, "
                "а в профила виждам неизползван подарък от кампания."
            ),
        }
    ]
    assert scenario["message"] == (
        "Щом пише „неизползван“, мога ли да го ползвам сега "
        "или да го дам на друг човек?"
    )
    assert "historical campaign terms" in scenario["focus"]
    assert "no expiry claim without evidence" in scenario["focus"]


def test_voucher_topup_does_not_create_new_campaign_bonus_entitlement() -> None:
    prompt = dev_gateway.build_skyai_system_prompt()
    architecture = " ".join(ARCHITECTURE_PATH.read_text(encoding="utf-8").split())
    cases = json.loads(QA_PRINCIPLES_PATH.read_text(encoding="utf-8"))
    scenarios = json.loads(COMPARE_SCENARIOS_PATH.read_text(encoding="utf-8"))

    assert "доплащане на разлика" in prompt
    assert "не създава нов бонус" in prompt
    assert "нов ваучер или директен BookNow" in prompt
    assert "конкретна дата/час не доказва BookNow" in prompt
    assert "получателят/доплащащият не става автоматично собственик" in prompt
    assert len(prompt) < 7100

    assert "Existing-voucher top-up campaign entitlement" in architecture
    assert "choosing a concrete date/time does not prove BookNow" in architecture
    assert "not a reservation-path classifier" in architecture
    assert "not answer-replacing post-processing" in architecture

    principle = next(case for case in cases if case["id"] == "voucher_topup_no_new_campaign_bonus")
    assert principle["source_threads"] == ["1533713798198984805"]
    assert "Redeeming or exchanging an already-existing voucher" in principle["principle"]
    assert "paying a top-up" in principle["principle"]
    assert "does not by itself create a new campaign bonus" in principle["principle"]
    assert "qualifying new voucher purchase or direct BookNow purchase" in principle["principle"]
    assert "Choosing a date/time does not prove BookNow" in principle["principle"]
    assert "original buyer/order email" in principle["principle"]

    scenario = next(case for case in scenarios if case["id"] == "voucher_topup_no_new_campaign_bonus")
    assert scenario["history"] == [
        {
            "role": "user",
            "content": (
                "Имам вече купен подаръчен ваучер на стойност. Избрах услуга, дата и час, "
                "и платих с карта само разликата в цената."
            ),
        }
    ]
    assert scenario["message"] == "Това доплащане прави ли ми нов бонусен безплатен полет от кампанията?"
    assert "reject categorical yes" in scenario["focus"]
    assert "date/time does not prove BookNow" in scenario["focus"]


def test_loaded_voucher_state_recovery_is_model_visible_without_manual_issuance() -> None:
    prompt = dev_gateway.build_skyai_system_prompt()
    architecture = " ".join(ARCHITECTURE_PATH.read_text(encoding="utf-8").split())
    support = public_tools.handle_skyai_support_knowledge(include_contacts=True)
    cases = json.loads(QA_PRINCIPLES_PATH.read_text(encoding="utf-8"))
    scenarios = json.loads(COMPARE_SCENARIOS_PATH.read_text(encoding="utf-8"))

    for required in (
        "Зареден съществуващ ваучер",
        "Моят ваучер",
        "Изчисти използването",
        "Потвърждавате ли изчистването на ваучера?",
        "Купи ваучер",
    ):
        assert required in prompt
    assert "Съществуващ ваучер не купува друг ваучер" in prompt
    assert "ръчно издаване" in prompt
    assert len(prompt) < 6700

    assert "Existing voucher vs new gift voucher ambiguity" in architecture
    assert "clearVoucher" in architecture
    assert "not a product-button keyword rule" in architecture
    assert "manual-issuance exception" in architecture

    boundary = support["vouchers"]["existing_value_voucher_gift_purchase_boundary"]
    assert boundary["existing_value_voucher_can_purchase_another_voucher"] is False
    assert boundary["existing_value_voucher_valid_use"] == "experience_reservation"
    assert boundary["separately_paid_new_gift_voucher_possible_when_product_facts_support_it"] is True

    loaded = boundary["loaded_existing_voucher_state"]
    assert loaded["product_page_state"] == {
        "canUseVoucher": True,
        "buy_voucher_button_visible": False,
        "reserve_voucher_button_visible": True,
        "shows_voucher_use_deposit_payment_state": True,
    }
    assert loaded["confirmation_text"] == "Потвърждавате ли изчистването на ваучера?"
    assert "clearVoucher" in loaded["clear_effect"]
    assert "Изчисти използването" in " ".join(loaded["recovery_steps"])
    assert "validated variant" in " ".join(loaded["recovery_steps"])

    principle = next(
        case
        for case in cases
        if case["id"] == "existing_voucher_gift_purchase_boundary"
    )
    assert principle["source_threads"] == [
        "sanitized_loaded_voucher_purchase_regression"
    ]
    assert "Loaded-voucher state hides Купи ваучер" in principle["principle"]
    assert "Product availability booleans must come from strict public product-detail facts" in principle["principle"]

    scenario_by_id = {case["id"]: case for case in scenarios}
    for scenario_id in (
        "loaded_voucher_state_clear_to_buy_gift_voucher",
        "product_detail_buy_voucher_restored_after_clear",
        "existing_voucher_cannot_buy_new_voucher",
        "separate_paid_new_gift_voucher_purchase",
        "existing_voucher_gift_path_ambiguous",
    ):
        assert scenario_id in scenario_by_id
    loaded_scenario = scenario_by_id[
        "loaded_voucher_state_clear_to_buy_gift_voucher"
    ]
    assert "Изчисти използването" in loaded_scenario["focus"]
    assert "normal purchase restoration" in loaded_scenario["focus"]


def test_issued_voucher_regift_lifecycle_state_persists_without_reissue_claims() -> None:
    prompt = dev_gateway.build_skyai_system_prompt()
    support = public_tools.handle_skyai_support_knowledge(include_contacts=True)
    architecture = " ".join(ARCHITECTURE_PATH.read_text(encoding="utf-8").split())
    cases = json.loads(QA_PRINCIPLES_PATH.read_text(encoding="utf-8"))
    scenarios = json.loads(COMPARE_SCENARIOS_PATH.read_text(encoding="utf-8"))

    for required in (
        "Дата на валидност („валиден до ...“) е evidence",
        "вече издаден ваучер",
        "запазвай issued-voucher state",
        "не преминавай към нова покупка",
        "не се преиздава като нов хартиен/пликов подаръчен ваучер",
        "не е средство за купуване на друг ваучер",
    ):
        assert required in prompt
    assert "13.10.2026" not in prompt
    assert len(prompt) < 6900

    lifecycle = support["vouchers"]["issued_voucher_regift_lifecycle"]
    assert lifecycle["validity_through_date_evidence"] == "voucher_already_issued"
    assert lifecycle["followup_state_boundary"] == (
        "same_issued_voucher_until_explicit_separate_paid_purchase_evidence"
    )
    assert lifecycle["new_gift_voucher_purchase_branch"] == {
        "separate_payment_required": True,
        "public_product_purchase_facts_required": True,
    }
    document_operations = lifecycle["existing_voucher_document_operations"]
    assert document_operations["paper_or_envelope_reissue_as_new_gift_voucher"] is False
    assert document_operations["manual_personalization_or_reprint_as_new_voucher"] is False
    assert document_operations["funds_another_voucher_purchase"] is False

    assert "Issued-voucher regift lifecycle" in architecture
    assert "valid-through date is state evidence" in architecture
    assert "not a runtime intent router" in architecture
    assert "not answer-replacing post-processing" in architecture

    principle = next(case for case in cases if case["id"] == "issued_voucher_regift_lifecycle")
    assert "validity-through date is evidence that the voucher is already issued" in principle["principle"]
    assert "preserve issued-voucher state across follow-up turns" in principle["principle"]
    assert "not switch to new-purchase instructions" in principle["principle"]
    assert "cannot be changed and reissued as a new paper/envelope gift voucher" in principle["principle"]
    assert "used as funds to buy another voucher" in principle["principle"]

    scenario_by_id = {case["id"]: case for case in scenarios}
    scenario = scenario_by_id["issued_voucher_regift_lifecycle_envelope_followup"]
    assert scenario["history"] == [
        {
            "role": "user",
            "content": "Имам ваучер, който е валиден до 13.10.2026, но още не искам да избирам дата за резервация.",
        }
    ]
    assert "в плик" in scenario["message"]
    assert "validity-through date means already issued" in scenario["focus"]
    assert "no new checkout/envelope delivery promise" in scenario["focus"]


def test_issued_voucher_regift_boundary_keeps_service_exchange_available() -> None:
    prompt = dev_gateway.build_skyai_system_prompt()
    support = public_tools.handle_skyai_support_knowledge(include_contacts=True)
    scenarios = json.loads(COMPARE_SCENARIOS_PATH.read_text(encoding="utf-8"))

    assert "Замени услуга" in prompt
    assert "не е конверсия/преиздаване в нов персонализиран ваучер" in prompt
    lifecycle = support["vouchers"]["issued_voucher_regift_lifecycle"]
    assert lifecycle["supported_existing_voucher_self_service"] == [
        "reservation",
        "service_exchange",
    ]
    assert lifecycle["service_exchange_changes_experience_not_voucher_document"] is True
    assert lifecycle["service_exchange_is_conversion_to_new_personalized_voucher"] is False

    scenario_by_id = {case["id"]: case for case in scenarios}
    scenario = scenario_by_id["issued_voucher_service_exchange_still_allowed"]
    assert "Замени услуга" in scenario["message"]
    assert "legitimate service exchange remains available" in scenario["focus"]
    assert "not conversion/reissue into a new personalized voucher" in scenario["focus"]


def test_issued_voucher_ownership_transfer_boundary_is_model_visible_without_internal_approver() -> None:
    prompt = dev_gateway.build_skyai_system_prompt()
    support = public_tools.handle_skyai_support_knowledge(include_contacts=True)
    architecture = " ".join(ARCHITECTURE_PATH.read_text(encoding="utf-8").split())
    cases = json.loads(QA_PRINCIPLES_PATH.read_text(encoding="utf-8"))

    for required in (
        "Смяна на услуга ≠ прехвърляне на собственост",
        "не махай ваучера от профила си за да го дадеш на друг",
        "не предавай сериен номер като self-service трансфер",
        "получателят не добавя ваучера в друг профил като supported flow",
        "оригиналният купувач/имейл от поръчката",
        "одобрение през официалния support процес",
        "не назовавай вътрешен одобряващ човек",
    ):
        assert required in prompt
    assert "Емил Ломлиев" not in prompt[prompt.index("Дата на валидност") :]

    lifecycle = support["vouchers"]["issued_voucher_regift_lifecycle"]
    transfer = lifecycle["ownership_transfer_boundary"]
    assert transfer["service_exchange_authorizes_transfer_or_regift"] is False
    assert transfer["remove_from_profile_serial_handoff_recipient_add_flow_supported"] is False
    assert transfer["recipient_can_authorize_transfer"] is False
    assert transfer["requires_verified_original_buyer_or_order_email_request"] is True
    assert transfer["requires_official_support_approval"] is True
    assert transfer["customer_visible_approver_identity"] is None
    assert transfer["support_escalation_reissues_new_personalized_paper_voucher"] is False

    presentation = lifecycle["same_voucher_informal_presentation"]
    assert presentation["allowed_if_customer_already_has_original_document"] is True
    assert presentation["changes_ownership_or_recipient_authorization"] is False
    assert presentation["changes_service_or_validity"] is False
    assert presentation["creates_new_official_paper_voucher_or_envelope"] is False

    assert "Issued-voucher ownership transfer boundary" in architecture
    assert "service exchange changes value usage, not ownership authority" in architecture
    assert "verified original-buyer/order-email request" in architecture
    assert "internal approver identity" in architecture

    principle = next(
        case for case in cases if case["id"] == "issued_voucher_ownership_transfer_boundary"
    )
    assert principle["source_threads"] == ["caa71cdd-f12b-5df1-8d3b-6b30097de873"]
    assert "not self-service" in principle["principle"]
    assert "verified original-buyer request" in principle["principle"]
    assert "without naming an internal approver" in principle["principle"]


def test_exact_failed_regift_multiturn_scenario_is_in_compare_fixtures() -> None:
    scenarios = json.loads(COMPARE_SCENARIOS_PATH.read_text(encoding="utf-8"))
    scenario = next(
        case
        for case in scenarios
        if case["id"] == "issued_voucher_ownership_transfer_multiturn_sc7"
    )

    assert scenario["history"] == [
        {
            "role": "user",
            "content": "Когато правя резервация, ваучерът е валиден до 13.10.2026 г., но не искам да определям дата. Как да постъпя?",
        },
        {
            "role": "user",
            "content": "Да, но искам да го изкарам като подарък в плик.",
        },
        {
            "role": "user",
            "content": "Този ваучер е подарен на мен, но аз не искам да го ползвам. Искам да го подаря на друг човек с друго преживяване и да изкарам ваучера на хартия.",
        },
    ]
    assert scenario["message"] == "Как тогава мога да го подаря на друг човек?"
    assert "SC7" in scenario["focus"]
    assert "must not recommend service exchange + profile removal + serial handoff + recipient profile add" in scenario["focus"]
    assert "current recipient cannot authorize it" in scenario["focus"]
    assert "verified original-buyer request plus approval" in scenario["focus"]
    assert "same-voucher informal presentation" in scenario["focus"]
    assert "separate paid new physical gift purchase" in scenario["focus"]


def test_loaded_voucher_compare_matrix_keeps_model_authored_qa_external() -> None:
    source = Path("scripts/skyai_v2_compare_matrix.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    runtime_functions = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name not in {"load_scenarios", "build_compare_payload"}
    ]
    runtime_source = "\n".join(
        ast.get_source_segment(source, node) or "" for node in runtime_functions
    )

    task_scenario_ids = (
        "loaded_voucher_state_clear_to_buy_gift_voucher",
        "existing_voucher_cannot_buy_new_voucher",
        "separate_paid_new_gift_voucher_purchase",
        "existing_voucher_gift_path_ambiguous",
        "issued_voucher_regift_lifecycle_envelope_followup",
        "issued_voucher_service_exchange_still_allowed",
        "issued_voucher_ownership_transfer_multiturn_sc7",
    )
    for scenario_id in task_scenario_ids:
        assert scenario_id not in runtime_source

    forbidden_helpers = (
        "_suggests_" + "manual_voucher_issuance",
        "_claims_" + "existing_voucher_can_buy_another",
        "_detects_" + "issued_voucher_regift",
        "_classifies_" + "voucher_lifecycle",
        "_detects_" + "ownership_transfer",
        "_scores_" + "regift_answer",
        "_routes_" + "voucher_transfer",
        "_renders_" + "transfer_template",
    )
    for helper_name in forbidden_helpers:
        assert helper_name not in source

    scenarios = json.loads(COMPARE_SCENARIOS_PATH.read_text(encoding="utf-8"))
    scenario_by_id = {case["id"]: case for case in scenarios}
    for scenario_id in task_scenario_ids:
        scenario = scenario_by_id[scenario_id]
        assert type(scenario["message"]) is str and scenario["message"].strip()
        assert type(scenario["focus"]) is str and scenario["focus"].strip()


def test_external_voucher_boundary_is_a_general_hermes_principle() -> None:
    prompt = dev_gateway.build_skyai_system_prompt()
    support = public_tools.handle_skyai_support_knowledge(include_contacts=True)
    cases = json.loads(QA_PRINCIPLES_PATH.read_text(encoding="utf-8"))
    principle = next(case for case in cases if case["id"] == "voucher_issuer_boundary")

    assert "приемай неуточнения ваучер за ваучер на SkyVision" in prompt
    assert "не питай рутинно за издателя" in prompt
    assert "конкретна причина да се съмняваш в съвместимостта" in prompt
    assert "Само ваучерите на SkyVision важат в SkyVision профила" in prompt
    assert "Ако клиентът посочи друг издател" in prompt
    assert "ваучерът не може да се добави тук" in prompt
    assert "при неясен произход първо го уточни" not in prompt

    issuer_scope = support["vouchers"]["issuer_scope"]
    assert issuer_scope["skyvision_issued_vouchers"]["profile_compatible"] is True
    assert issuer_scope["externally_issued_vouchers"]["profile_compatible"] is False
    assert issuer_scope["catalog_overlap_changes_issuer_or_compatibility"] is False
    assert issuer_scope["compatibility_is_issuer_scoped"] is True
    assert "обичайно означава ваучер" in issuer_scope["unspecified_origin_in_skyvision_chat"]
    addition_facts = support["vouchers"]["customer_panel"]["addition_problem_facts"]
    assert "латиница" in addition_facts["serial_format"]
    assert addition_facts["possible_issuer_mismatch"] is True
    assert "особен статус" in " ".join(addition_facts["other_possible_states"])

    assert principle["source_threads"] == ["1530167380133544067", "1530561454191673356"]
    assert "without turning the issuer check into a routine question" in principle["principle"]
    assert "normally be treated as SkyVision-issued" in principle["principle"]
    assert "concrete reason to doubt compatibility" in principle["principle"]
    assert "identifies another platform, seller, or provider" in principle["principle"]


def test_customer_reply_contact_distinguishes_automated_sender() -> None:
    prompt = dev_gateway.build_skyai_system_prompt()
    support = public_tools.handle_skyai_support_knowledge(include_contacts=True)
    cases = json.loads(QA_PRINCIPLES_PATH.read_text(encoding="utf-8"))
    principle = next(case for case in cases if case["id"] == "customer_reply_contact")

    assert "Писмен контакт с екипа: info@skyvision.bg" in prompt
    assert "reservations@skyvision.bg е автоматичен адрес" in prompt
    assert "не канал за клиентски отговори" in prompt

    reservation_contact = support["reservation_support"]
    assert reservation_contact["customer_contact_email"] == "info@skyvision.bg"
    automated = reservation_contact["automated_notification_address"]
    assert automated["email"] == "reservations@skyvision.bg"
    assert automated["role"] == "автоматични известия за резервации"
    assert automated["monitored"] is True
    assert automated["accepts_customer_replies"] is False
    assert support["official_contacts"]["email"] == "info@skyvision.bg"

    assert principle["source_threads"] == ["1530546975835947061"]
    assert "use info@skyvision.bg" in principle["principle"]
    assert "not a customer reply channel" in principle["principle"]


def test_pilot_provider_phone_is_confirmation_email_context_not_public_page_script() -> None:
    prompt = dev_gateway.build_skyai_system_prompt()
    support = public_tools.handle_skyai_support_knowledge(include_contacts=True)
    architecture = " ".join(ARCHITECTURE_PATH.read_text(encoding="utf-8").split())
    cases = json.loads(QA_PRINCIPLES_PATH.read_text(encoding="utf-8"))
    scenarios = json.loads(COMPARE_SCENARIOS_PATH.read_text(encoding="utf-8"))

    assert "пилот/изпълнител/организатор" in prompt
    assert "след успешна резервация" in prompt
    assert "имейла за потвърждение" in prompt
    assert "публичната продуктова страница" in prompt
    assert "не измисляй публична секция" in prompt
    assert "номер на пилот" in prompt
    assert len(prompt) < 7100

    reservation_support = support["reservation_support"]
    provider_contact = reservation_support["provider_contact_details"]
    assert provider_contact["available_after_successful_reservation"] is True
    assert provider_contact["delivery_channel"] == "email"
    assert provider_contact["source"] == "reservation_confirmation_email"
    assert provider_contact["public_product_page_contains_direct_phone"] is False
    assert provider_contact["official_support_contact_available"] is True
    assert "missing_details_next_step" not in provider_contact
    assert "customer_safe_summary" not in provider_contact
    assert "direct_provider_phone" not in json.dumps(provider_contact, ensure_ascii=False)

    assert "Provider/pilot contact details are reservation-confirmation context" in architecture
    assert "not a public-page section detector" in architecture
    assert "not a product-specific answer template" in architecture

    principle = next(case for case in cases if case["id"] == "pilot_provider_contact_confirmation_email")
    assert principle["source_threads"] == ["case:skyai-pilot-phone-confirmation-email-20260804"]
    assert "successful reservation" in principle["principle"]
    assert "confirmation email" in principle["principle"]
    assert "public product page" in principle["principle"]
    assert "never invent" in principle["principle"]

    scenario = next(case for case in scenarios if case["id"] == "pilot_provider_phone_missing_public_section")
    assert scenario["history"] == [
        {
            "role": "user",
            "content": "Къде мога да намеря номера на пилота?",
        },
        {
            "role": "user",
            "content": "Става дума за въвеждащия полет-урок със самолет над Рилски езера.",
        },
    ]
    assert scenario["message"] == "Не намирам такава секция на страницата. Къде е телефонът?"
    assert "confirmation email" in scenario["focus"]
    assert "no public page phone/section claim" in scenario["focus"]
    assert "preserve provider/location/timing/weather public facts" in scenario["focus"]

    positive = next(case for case in scenarios if case["id"] == "pilot_provider_public_facts_still_usable")
    assert positive["message"] == (
        "Можеш ли да ми припомниш изпълнителя, локацията и дали трябва да се съобразя с времето?"
    )
    assert "provider/location/timing/weather facts remain usable" in positive["focus"]
    assert "do not suppress public product facts" in positive["focus"]


def test_reservation_voucher_path_ambiguity_is_hermes_principle() -> None:
    prompt = dev_gateway.build_skyai_system_prompt()
    architecture = " ".join(ARCHITECTURE_PATH.read_text(encoding="utf-8").split())
    cases = json.loads(QA_PRINCIPLES_PATH.read_text(encoding="utf-8"))
    scenarios = json.loads(COMPARE_SCENARIOS_PATH.read_text(encoding="utf-8"))

    assert "не е ясно дали има/ползва ваучер" in prompt
    assert "Моят ваучер/профил" in prompt
    assert "директен BookNow/карта само без ваучер" in prompt
    assert "Не твърди задължителни UI стъпки" in prompt
    assert "tool/public evidence" in prompt
    assert len(prompt) < 7100

    assert "Reservation path ambiguity is Hermes reasoning context" in architecture
    assert "not a runtime intent router" in architecture
    assert "direct BookNow/card payment only when no voucher is being used" in architecture
    assert "without bounded public facts or tool evidence" in architecture

    principle = next(case for case in cases if case["id"] == "reservation_voucher_path_ambiguity")
    assert principle["source_threads"] == ["real_customer_discord_reservation_voucher_ambiguity"]
    assert "do not assume direct BookNow/card payment" in principle["principle"]
    assert "existing SkyVision voucher" in principle["principle"]
    assert "product reservation voucher option" in principle["principle"]
    assert "buying a voucher only" in principle["principle"]
    assert "unless bounded facts or tools supply them" in principle["principle"]

    scenario = next(case for case in scenarios if case["id"] == "reservation_voucher_path_ambiguity")
    assert "voucher/payment path is unknown" in scenario["focus"]
    assert "do not assume direct BookNow/card payment" in scenario["focus"]


def test_confirmed_reservation_self_cancellation_is_general_principle() -> None:
    prompt = dev_gateway.build_skyai_system_prompt()
    support = public_tools.handle_skyai_support_knowledge(include_contacts=True)
    architecture = " ".join(ARCHITECTURE_PATH.read_text(encoding="utf-8").split())
    cases = json.loads(QA_PRINCIPLES_PATH.read_text(encoding="utf-8"))
    scenarios = json.loads(COMPARE_SCENARIOS_PATH.read_text(encoding="utf-8"))

    assert "потвърдена/предстояща резервация" in prompt
    assert "профил -> Резервации" in prompt
    assert "Анулиране на резервацията" in prompt
    assert "не казвай, че екипът трябва да я анулира" in prompt
    assert "не измисляй универсален срок" in prompt
    assert "точната услуга вече е ясна" in prompt
    assert "skyai_product_detail" in prompt
    assert "структурния cancellationPolicy" in prompt
    assert "описателен текст" in prompt
    assert "след успешно анулиране" in prompt
    assert prompt.index("Анулиране на резервацията") < prompt.index("след успешно анулиране")
    assert "info@skyvision.bg" in prompt

    reservation_support = support["reservation_support"]
    assert reservation_support["customer_profile_section"] == "Профил -> Резервации"
    assert reservation_support["self_service_cancel_action"] == "Анулиране на резервацията"
    assert reservation_support["public_terms_sections"] == ["1.2", "4.1", "17.2", "17.4", "17.5"]
    assert reservation_support["provider_defined_change_conditions"] is True
    assert reservation_support["platform_enforces_cancel_cutoff"] is True
    assert reservation_support["global_cancel_hours"] is None
    assert reservation_support["self_service_cancel_after_cutoff_available"] is False
    assert "reservation/cancel/" in reservation_support["customer_cancel_endpoint_pattern"]
    assert "direct_email" not in reservation_support

    principle = next(case for case in cases if case["id"] == "confirmed_reservation_self_cancellation")
    assert principle["source_threads"] == ["sanitized_qa_1533000762970341406"]
    assert "self-service path first" in principle["principle"]
    assert "Do not invent a universal cancellation window" in principle["principle"]
    assert "only then suggest contacting" in principle["principle"]
    assert "After successful cancellation and voucher release" in principle["principle"]

    scenario_ids = {case["id"] for case in scenarios}
    assert {
        "confirmed_reservation_wants_another_experience",
        "reservation_cancel_cutoff_unknown",
        "reservation_cancel_unavailable_or_deadline_passed",
        "reservation_already_cancelled_voucher_exchange",
        "reservation_self_cancel_reject_team_only",
        "reservation_identified_service_eight_hour_policy",
        "reservation_identified_service_no_free_cancellation",
        "reservation_detail_fetch_policy_unknown",
        "reservation_prior_turn_service_no_redundant_clarification",
        "reservation_ambiguous_service_clarification",
        "reservation_reject_stale_prose_and_universal_hours",
    } <= scenario_ids
    assert "Confirmed reservation self-cancellation is Hermes reasoning context" in architecture
    assert "not a runtime intent router" in architecture
    assert "provider-defined conditions" in architecture
    assert "no universal cancellation window" in architecture


def test_campaign_tool_returns_fact_pack_not_customer_script() -> None:
    result = public_tools.handle_skyai_campaign_knowledge()
    serialized = json.dumps(result, ensure_ascii=False)

    assert result["tool_contract"]["purpose"] == "public_facts_only"
    assert result["tool_contract"]["reasoning_owner"] == "hermes"
    assert "customer_facing_flow" not in serialized
    assert "do_not_say" not in serialized
    assert "tone_anchors" not in serialized
    assert "sales_tone" not in serialized


def _payload_keys(value) -> set[str]:
    if isinstance(value, dict):
        keys = set(value)
        for child in value.values():
            keys.update(_payload_keys(child))
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for child in value:
            keys.update(_payload_keys(child))
        return keys
    return set()


def test_customer_tools_return_facts_not_instruction_keys() -> None:
    payloads = [
        public_tools.handle_skyai_campaign_knowledge(),
        public_tools.handle_skyai_support_knowledge(include_contacts=True),
    ]
    forbidden_instruction_or_reply_keys = {
        "answer_guidance",
        "guidance",
        "missing_details_next_step",
        "customer_safe_summary",
        "recommended_action",
        "recommended_response",
        "ready_made_reply",
        "reply_template",
        "when_to_use",
        "customer_facing_flow",
    }

    for payload in payloads:
        keys = _payload_keys(payload)
        assert keys.isdisjoint(forbidden_instruction_or_reply_keys)
        assert not any(key.endswith("_guidance") for key in keys)


def test_catalog_tool_has_no_backend_persona_or_keyword_policy() -> None:
    source = Path("plugins/skyai_customer/public_tools.py").read_text(encoding="utf-8")

    assert "_guidance" not in source

    forbidden_symbols = {
        "_CALM_QUERY_TOKENS",
        "_CALM_PRODUCT_SIGNALS",
        "_EXTREME_PRODUCT_SIGNALS",
        "_HIGH_ADRENALINE_PRODUCT_SIGNALS",
        "_NARROW_SPECIFIC_QUERY_SIGNALS",
        "_NEGATABLE_PRODUCT_TOKENS",
        "_query_traits",
        "_product_relevance_score",
        "_location_relevance_score",
        "_recipient_fit_score",
        "_diversify_ranked_products",
        "_prefer_nearby_results_when_available",
        "_catalog_recipient_context",
        "recipient_context",
        "broad_discovery",
        "single_recipient_gift",
    }
    for symbol in forbidden_symbols:
        assert symbol not in source


def test_voice_handoff_has_no_transcript_phrase_list() -> None:
    source = Path("plugins/skyai_customer/dev_gateway.py").read_text(encoding="utf-8")

    assert "VOICE_HUMAN_HANDOFF_TERMS" not in source
    assert "_voice_handoff_requested" not in source
    assert "skyai_voice_transfer_to_human" in source
    assert "voice_action_source" in source


def test_qa_feedback_is_evaluation_material_not_runtime_policy() -> None:
    cases = json.loads(QA_PRINCIPLES_PATH.read_text(encoding="utf-8"))

    assert len(cases) >= 16
    assert {case["id"] for case in cases} >= {
        "bonus_transfer_not_direct_yes",
        "respect_negative_clarification",
        "location_priority",
        "booknow_refund_language",
        "no_keyword_backend_patches",
        "session_context_concision",
        "voucher_issuer_boundary",
        "customer_reply_contact",
    }
    assert all("principle" in case for case in cases)
    assert all("scoring" in case for case in cases)


def test_service_cancellation_policy_uses_hybrid_catalog_detail_facts() -> None:
    architecture = " ".join(ARCHITECTURE_PATH.read_text(encoding="utf-8").split())
    cases = json.loads(QA_PRINCIPLES_PATH.read_text(encoding="utf-8"))
    scenarios = json.loads(COMPARE_SCENARIOS_PATH.read_text(encoding="utf-8"))

    assert "hybrid catalog search plus bounded product detail refresh" in architecture
    assert "structured `cancellationPolicy`" in architecture
    assert "not free-form product description prose" in architecture
    assert "no N+1 detail fetch" in architecture

    principle = next(case for case in cases if case["id"] == "service_specific_cancellation_policy")
    assert "current public product detail" in principle["principle"]
    assert "ask one concise service clarification" in principle["principle"]
    assert "not infer from prose" in principle["principle"]
    assert "no universal cancellation window" in principle["principle"]

    scenario_by_id = {case["id"]: case for case in scenarios}
    assert "8-hour structured cancellationPolicy" in scenario_by_id["reservation_identified_service_eight_hour_policy"]["focus"]
    assert "no redundant service clarification" in scenario_by_id["reservation_prior_turn_service_no_redundant_clarification"]["focus"]
    assert "one concise service clarification" in scenario_by_id["reservation_ambiguous_service_clarification"]["focus"]


def test_skyai_architecture_guardrails_absent_in_customer_plugin() -> None:
    combined = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in (
            "plugins/skyai_customer/public_tools.py",
            "plugins/skyai_customer/dev_gateway.py",
        )
    )
    forbidden_runtime_markers = (
        "IntentClassifier",
        "intent_classifier",
        "keyword_classifier",
        "mandatory_question_router",
        "answer_template_selector",
        "template_selector",
        "answer_replacing_post_processing",
        "response_replacing_post_processing",
        "universal_cancellation_hours",
    )
    for marker in forbidden_runtime_markers:
        assert marker not in combined

    product = public_tools.handle_skyai_product_detail(product_path="")
    payload_keys = _payload_keys(product)
    assert "guidance" not in payload_keys
    assert "answer_guidance" not in payload_keys
    assert "when_to_use" not in payload_keys
    assert "suggested_question" not in payload_keys
    assert "recommended_response" not in payload_keys



def test_universal_value_voucher_is_model_first_prompt_and_evaluation_material() -> None:
    expected_principle = (
        "Подарък без преживяване: facts за „Подаръчен ваучер на стойност“; съществува; "
        "купувачът избира сума, получателят после избира. Без наложено преживяване; model facts, not router/template."
    )
    prompt = dev_gateway.build_skyai_system_prompt()
    principles = json.loads(QA_PRINCIPLES_PATH.read_text(encoding="utf-8"))
    scenarios = json.loads(COMPARE_SCENARIOS_PATH.read_text(encoding="utf-8"))

    assert dev_gateway.SKYAI_UNIVERSAL_VALUE_VOUCHER_PRINCIPLE == expected_principle
    assert expected_principle in prompt

    principle = next(
        case for case in principles if case["id"] == "universal_value_voucher_non_specific_gift"
    )
    assert principle["source_threads"] == [
        "case:skyai-voucher-value-20260807-1535227388445720779"
    ]
    assert "universal value voucher exists" in principle["principle"]
    assert "recipient chooses the experience later" in principle["principle"]
    assert "do not invent or force a selected experience" in principle["principle"]
    assert "not a keyword router or answer template" in principle["principle"]

    scenario = next(
        case for case in scenarios if case["id"] == "universal_value_voucher_non_specific_gift"
    )
    assert scenario["message"] == "Искам да не е конкретен"
    assert "universal value voucher exists" in scenario["focus"]
    assert "non-specific gift" in scenario["focus"]
    assert "€25 / 48.89 BGN" in scenario["focus"]
    assert "https://skyvision.bg/gift-details/voucher-gift/" in scenario["focus"]
    assert "no invented selected experience" in scenario["focus"]
