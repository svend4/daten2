"""Переносимая репутация по цеховой модели (поверх §7 — обязательства).

ПОЧЕМУ ЗВЁЗДОЧКИ НЕ РАБОТАЮТ, А РЕКОМЕНДАТЕЛЬНОЕ ПИСЬМО РАБОТАЕТ
-----------------------------------------------------------------
Рейтинг на чужом сайте — это не репутация, а запись в чужой базе. Он не
переносится (уйдя с площадки, человек начинает с нуля), не проверяется (вы
видите среднее, но не видите работ) и не привязан ни к чему (пять звёзд можно
поставить за несуществующий заказ).

Средневековый цех решал ту же задачу без центральной власти и решал лучше:
квалификацию подтверждал цех, клеймо мастера стояло на изделии, а переносимым
носителем доверия было РЕКОМЕНДАТЕЛЬНОЕ ПИСЬМО — документ о КОНКРЕТНОЙ
выполненной работе, который подмастерье уносил с собой в другой город. Письмо
можно было предъявить, и его можно было проверить: названы заказчик, работа и
мастер, поставивший клеймо.

В NPP-Act для такого письма уже есть всё основание, и это главное, что здесь
используется. Двустороннее обязательство (§7, `agent.commit_two_party`)
записывается в ДВА независимых журнала — заказчика и исполнителя — с общим
`commitment_id`, и у каждой записи есть хэш в своей цепи. Значит, свидетельство
о работе можно не просто ВЫДАТЬ, а ПРЕДЪЯВИТЬ и ПРОВЕРИТЬ: проверяющий берёт
оба журнала и убеждается, что работа действительно была, а не объявлена.

ЧЕМ ЭТО ОТЛИЧАЕТСЯ ОТ `reputation.endorse` В ЦЕХЕ (act/services/freelance)
--------------------------------------------------------------------------
Сервис цеха тоже привязывает рекомендацию к работе, а не к профилю, — но хранит
её у себя. Это рейтинг на чужом сайте, пусть и устроенный честно: чтобы его
прочитать, нужно спросить сервис, и живёт он ровно столько, сколько живёт
сервис. `Credential` — переносимая форма того же факта: она уходит ВМЕСТЕ С
ИСПОЛНИТЕЛЕМ и проверяется третьей стороной, которая с этим сервисом никогда
не разговаривала. Сервис остаётся местом, где работа состоялась; свидетельство
становится тем, что от неё остаётся на руках.

ГЛАВНОЕ УСЛОВИЕ ВЫДАЧИ
----------------------
Свидетельство без подтверждённой работы выдать НЕЛЬЗЯ: `issue()` отказывает,
если обязательства нет в обеих цепях или цепи не целы. В этом вся разница со
звёздочками — выдать можно только то, что уже произошло.

ПРО ПОДПИСЬ: ЧЕСТНАЯ ОГОВОРКА (НЕ ПРОПУСКАТЬ)
---------------------------------------------
Клеймо мастера здесь — HMAC-SHA256 из стандартной библиотеки. Это
СИММЕТРИЧНАЯ схема, и она НЕ решает задачу публичной проверки:

  * проверить подпись может только тот, у кого есть тот же секрет, что у issuer;
  * кто может проверить — тот может и подделать: ключ один и тот же.

Для настоящей переносимости нужна асимметричная подпись (Ed25519: секрет у
issuer, публичный ключ у всех, подделать нельзя), а её в stdlib Python без
внешних зависимостей нет. Притворяться, что HMAC её заменяет, здесь не будем:
`alg` объявлен в свидетельстве полем, а `verify()` без ключа прямо говорит
«подпись не проверена», а не «свидетельство недействительно».

И тем не менее свидетельство остаётся проверяемым без всякого ключа — потому
что доказывает работу не подпись, а ДВЕ НЕЗАВИСИМЫЕ ХЭШ-ЦЕПИ. `work_proven()`
проверяет ровно это: обязательство есть в журналах обеих сторон, цепи целы,
issuer и subject — действительно его стороны, и описанная работа совпадает с
предметом обязательства. Подпись добавляет к этому только одно: что письмо
написал именно тот, кто называется issuer. Поэтому подмена issuer ловится
здесь ДВАЖДЫ — и подписью (если ключ есть), и записью в цепи (всегда).

Зависимостей нет: hmac, hashlib, json из стандартной библиотеки.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator, Mapping

from .agent import Commitment
from .ledger import Ledger, LedgerError

#: Шкала оценки. Пять градаций, как у цеховой записи «похвально — с оговорками»:
#: шире шкала не делает её точнее, зато делает несравнимой между цехами.
RATING_MIN, RATING_MAX = 1, 5

#: Алгоритм клейма. Строкой и в самом свидетельстве — чтобы предъявленное
#: письмо само говорило, чем оно подписано, а не оставляло это допущением.
ALG_HMAC = "hmac-sha256"

#: Метки домена. Без них один и тот же ключ, использованный где-то ещё под
#: HMAC, дал бы совпадающие значения, и подпись свидетельства можно было бы
#: добыть из постороннего протокола.
_SIG_LABEL = b"npp-act/credential/signature/v1\x00"
_KID_LABEL = b"npp-act/credential/key-id/v1"


class CredentialError(RuntimeError):
    """Свидетельство нельзя выдать: работы, под которую его просят, нет."""


def _canonical(obj: Any) -> str:
    """Каноническая форма JSON — та же, что у журнала (ledger._canonical).

    Повторена здесь намеренно, а не импортирована приватным именем: от этой
    формы зависит ПОДПИСЬ, и она не должна меняться вместе с внутренностями
    чужого модуля. Правила те же: сортировка ключей, компактные разделители,
    юникод как есть.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _as_bytes(key: str | bytes) -> bytes:
    return key if isinstance(key, bytes) else str(key).encode("utf-8")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def key_id(key: str | bytes) -> str:
    """Отпечаток ключа: «как выглядит клеймо», не раскрывая самого клейма.

    Нужен, чтобы в портфолио из десяти писем было видно, что три из них
    подписаны одним и тем же ключом. Секрет из отпечатка не выводится: это
    HMAC по фиксированной метке, а не хэш ключа.
    """
    return "kid_" + hmac.new(_as_bytes(key), _KID_LABEL, hashlib.sha256).hexdigest()[:16]


def _sign(body: dict[str, Any], key: str | bytes) -> str:
    msg = _SIG_LABEL + _canonical(body).encode("utf-8")
    return "hs256:" + hmac.new(_as_bytes(key), msg, hashlib.sha256).hexdigest()


# ────────────────────────────────────────────────────────────────────────────
# Само свидетельство
# ────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Credential:
    """Рекомендательное письмо о конкретной выполненной работе.

    Поле `subject` здесь — КОМУ выдано (исполнитель), а не предмет работы;
    предмет лежит в `work`. Это расходится с `Commitment.subject`, где
    `subject` — именно предмет сделки, и расхождение названо вслух, чтобы его
    не приходилось выяснять по коду: письмо адресовано человеку, обязательство
    заключено о работе.

    `anchors` — главное поле: профиль стороны → хэш записи `commitment` в её
    цепи. Без него письмо было бы заявлением; с ним оно предъявляемо, потому
    что указывает на две конкретные строки в двух независимых журналах.

    Класс неизменяемый (`frozen`): подпись стоит под значениями, а не рядом с
    ними. Поправить оценку в полученном письме можно только создав новый
    объект (`dataclasses.replace`) — и подпись при этом перестанет сходиться,
    что и требуется.
    """

    commitment_id: str
    issuer: str
    subject: str
    work: str
    rating: int
    note: str = ""
    issued_at: str = ""
    anchors: dict[str, str] = field(default_factory=dict)
    service: str = ""
    verb: str = ""
    #: Публичная ссылка на работу, выданная сервисом (например work_ref цеха).
    #: Непубличный токен обязательства (§10.3) в письмо не попадает.
    work_ref: str = ""
    alg: str = ALG_HMAC
    key_id: str = ""
    signature: str = ""

    # ---------- форма для подписи и переноса ----------

    def signed_body(self) -> dict[str, Any]:
        """Всё, что покрыто подписью: само письмо без самой подписи."""
        return {
            "commitment_id": self.commitment_id,
            "issuer": self.issuer,
            "subject": self.subject,
            "work": self.work,
            "rating": self.rating,
            "note": self.note,
            "issued_at": self.issued_at,
            "anchors": dict(self.anchors),
            "service": self.service,
            "verb": self.verb,
            "work_ref": self.work_ref,
            "alg": self.alg,
            "key_id": self.key_id,
        }

    def to_dict(self) -> dict[str, Any]:
        d = self.signed_body()
        d["signature"] = self.signature
        return d

    def to_json(self) -> str:
        """Письмо уезжает с исполнителем — значит, должно быть переносимым файлом."""
        return _canonical(self.to_dict())

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> "Credential":
        return Credential(
            commitment_id=str(d.get("commitment_id", "")),
            issuer=str(d.get("issuer", "")),
            subject=str(d.get("subject", "")),
            work=str(d.get("work", "")),
            rating=int(d.get("rating", 0)),
            note=str(d.get("note", "")),
            issued_at=str(d.get("issued_at", "")),
            anchors={str(k): str(v) for k, v in dict(d.get("anchors") or {}).items()},
            service=str(d.get("service", "")),
            verb=str(d.get("verb", "")),
            work_ref=str(d.get("work_ref", "")),
            alg=str(d.get("alg", ALG_HMAC)),
            key_id=str(d.get("key_id", "")),
            signature=str(d.get("signature", "")),
        )

    @staticmethod
    def from_json(raw: str) -> "Credential":
        return Credential.from_dict(json.loads(raw))

    # ---------- мелочи ----------

    @property
    def parties(self) -> list[str]:
        return sorted(self.anchors)

    def signed_by(self, key: str | bytes) -> bool:
        """Сходится ли клеймо с этим ключом. Сравнение — compare_digest."""
        if not self.signature:
            return False
        return hmac.compare_digest(self.signature, _sign(self.signed_body(), key))

    def __str__(self) -> str:
        return (f"{self.subject} ← {self.issuer}: {self.work} "
                f"[{self.rating}/{RATING_MAX}] {self.commitment_id}")


# ────────────────────────────────────────────────────────────────────────────
# Проверка работы по двум цепям — без всякого ключа
# ────────────────────────────────────────────────────────────────────────────


def _find_by_hash(led: Ledger, h: str):
    for rec in led:
        if rec.hash == h:
            return rec
    return None


def _ref_seen(led: Ledger, ref: str) -> bool:
    """Встречается ли публичная ссылка на работу в журнале стороны.

    Поиск подстрокой по канонической форме записи — и это осознанная грубость.
    NPP-Act 1.0 не объявляет, в каком поле ответа сервис отдаёт публичную
    ссылку на работу (`work_ref` в цехе, что-нибудь другое в другом сервисе),
    поэтому проверять по имени поля было бы проверкой одного сервиса, а не
    протокола. Это тот же аргумент, что у `calendar.when`: формату не хватает
    поля, и честный поиск текстом показывает нехватку, а не прячет её.
    """
    if not ref:
        return True
    for rec in led:
        if rec.kind in ("execution", "outcome", "commitment") and ref in _canonical(rec.payload):
            return True
    return False


def work_proven(
    credential: Credential,
    ledgers: Mapping[str, Ledger],
    *,
    require_ref: bool = True,
) -> tuple[bool, list[str]]:
    """Была ли работа. Ключ issuer не нужен — доказывают цепи, а не подпись.

    Это самая важная функция модуля: именно она отвечает на вопрос, который
    нельзя задать звёздочкам. Проверяется семь вещей:

      1. письмо вообще привязано к обязательству (непустой commitment_id);
      2. оценка в объявленной шкале;
      3. issuer не выдал письмо сам себе;
      4. в письме есть привязки обеих сторон и журналы обеих предъявлены;
      5. каждая цепь цела (разрыв — это уже ответ, а не техническая деталь);
      6. указанная запись есть в цепи, она `commitment`, и это ТО САМОЕ
         обязательство, а не другая запись с подходящим хэшем;
      7. issuer и subject — действительно стороны этого обязательства, а
         описанная работа совпадает с его предметом.

    Пункт 7 и ловит подмену issuer без всякой подписи: переписав себя в поле
    `issuer`, подделыватель не сможет переписать `parties` в двух чужих цепях.
    """
    reasons: list[str] = []

    if not credential.commitment_id:
        reasons.append("свидетельство не привязано к обязательству (пустой commitment_id)")
    if not isinstance(credential.rating, int) or not (
            RATING_MIN <= credential.rating <= RATING_MAX):
        reasons.append(f"оценка {credential.rating!r} вне шкалы {RATING_MIN}..{RATING_MAX}")
    if credential.issuer and credential.issuer == credential.subject:
        reasons.append("issuer и subject совпадают: свидетельство самому себе ничего не значит")
    if not credential.anchors:
        reasons.append("в свидетельстве нет привязок к журналам — предъявлять нечего")

    for who, role in ((credential.issuer, "issuer"), (credential.subject, "subject")):
        if who and who not in credential.anchors:
            reasons.append(f"нет хэша-привязки для стороны '{who}' ({role})")

    for party, h in sorted(credential.anchors.items()):
        led = ledgers.get(party)
        if led is None:
            reasons.append(f"журнал стороны '{party}' не предъявлен — проверять нечем")
            continue
        try:
            led.verify()
        except LedgerError as e:
            reasons.append(f"цепь стороны '{party}' нарушена: {e}")
            continue

        rec = _find_by_hash(led, h)
        if rec is None:
            reasons.append(
                f"в журнале '{party}' нет записи {h[:12]}… — такого обязательства не было")
            continue
        if rec.kind != "commitment":
            reasons.append(
                f"запись {h[:12]}… в журнале '{party}' — не обязательство (kind={rec.kind})")
            continue

        payload = rec.payload if isinstance(rec.payload, dict) else {}
        cid = str(payload.get("commitment_id") or "")
        if cid != credential.commitment_id:
            reasons.append(
                f"запись в журнале '{party}' относится к другому обязательству ({cid or '—'})")
            continue

        parties = [str(p) for p in (payload.get("parties") or [])]
        for who, role in ((credential.issuer, "issuer"), (credential.subject, "subject")):
            if who and parties and who not in parties:
                reasons.append(
                    f"{role} '{who}' не является стороной обязательства "
                    f"(в записи journal '{party}': {', '.join(parties)})")

        declared = str(payload.get("subject") or "")
        if credential.work and declared and credential.work != declared:
            reasons.append(
                f"работа в свидетельстве не совпадает с предметом обязательства: "
                f"'{credential.work}' ≠ '{declared}'")
        svc = str(payload.get("service") or "")
        if credential.service and svc and credential.service != svc:
            reasons.append(
                f"сервис в свидетельстве ('{credential.service}') не совпадает "
                f"с сервисом обязательства ('{svc}')")

    # Публичная ссылка на работу должна быть видна там, где её получили:
    # issuer принимал работу сам, значит ответ сервиса лежит в ЕГО журнале.
    if require_ref and credential.work_ref:
        led = ledgers.get(credential.issuer)
        if led is not None and not _ref_seen(led, credential.work_ref):
            reasons.append(
                f"ссылка на работу '{credential.work_ref}' не встречается в журнале issuer")

    # Дубли читать человеку незачем: один и тот же изъян мог сработать на обеих
    # сторонах, но причина у него одна.
    unique: list[str] = []
    for r in reasons:
        if r not in unique:
            unique.append(r)
    return (not unique), unique


# ────────────────────────────────────────────────────────────────────────────
# Выдача
# ────────────────────────────────────────────────────────────────────────────


def issue(
    commitment: Commitment,
    ledgers: Mapping[str, Ledger],
    issuer: str,
    subject: str,
    rating: int,
    note: str = "",
    *,
    key: str | bytes | None = None,
    work: str = "",
    work_ref: str = "",
    service: str = "",
    verb: str = "",
    issued_at: str | None = None,
) -> Credential:
    """Выдать свидетельство о выполненной работе.

    Условие выдачи не формальность, а весь смысл модуля: обязательство ДОЛЖНО
    быть в обеих цепях, цепи ДОЛЖНЫ быть целы, issuer и subject ДОЛЖНЫ быть его
    сторонами. Иначе — `CredentialError`, и никакого письма.

    Проверка здесь строже `Commitment.verified_by()`: тот ищет только хэш в
    цепи, то есть принял бы обязательство, у которого в журнале лежит ДРУГОЙ
    `commitment_id`. Для карты времени этого достаточно, для письма, которое
    предъявляют третьей стороне, — нет.

    `key` — секрет issuer. Без него письмо выдаётся неподписанным: это не
    ошибка, а честное состояние («работа доказуема, клейма нет»), и портфолио
    такое письмо отличит от подписанного.
    """
    if issuer == subject:
        raise CredentialError("свидетельство самому себе не выдаётся")
    if not isinstance(rating, int) or not (RATING_MIN <= rating <= RATING_MAX):
        raise CredentialError(f"оценка должна быть целым {RATING_MIN}..{RATING_MAX}, получено {rating!r}")

    parties = list(commitment.parties or [])
    for who, role in ((issuer, "issuer"), (subject, "subject")):
        if parties and who not in parties:
            raise CredentialError(
                f"{role} '{who}' не сторона обязательства {commitment.id} "
                f"({', '.join(parties)})")

    anchors = {str(k): str(v) for k, v in dict(commitment.hashes or {}).items()}
    if not anchors:
        raise CredentialError(
            f"обязательство {commitment.id} не несёт хэшей записей — "
            "оно не было записано в журналы сторон")
    for who in (issuer, subject):
        if who not in anchors:
            raise CredentialError(
                f"обязательство {commitment.id} не записано в журнал стороны '{who}'")

    draft = Credential(
        commitment_id=commitment.id,
        issuer=issuer,
        subject=subject,
        work=work or commitment.subject,
        rating=rating,
        note=note,
        issued_at=issued_at or now_iso(),
        anchors=anchors,
        service=service,
        verb=verb,
        work_ref=work_ref,
        key_id=key_id(key) if key is not None else "",
    )

    # Та же самая проверка, которой потом будет пользоваться проверяющий.
    # Выдавать по более слабому правилу, чем проверяют, — способ выдать письмо,
    # которое не пройдёт первую же проверку.
    ok, reasons = work_proven(draft, ledgers)
    if not ok:
        raise CredentialError(
            f"работа под обязательством {commitment.id} не подтверждена: " + "; ".join(reasons))

    if key is None:
        return draft
    return sign(draft, key)


def sign(credential: Credential, key: str | bytes) -> Credential:
    """Поставить клеймо на письмо (или переставить его другим ключом).

    Отдельной функцией — потому что мастер может подписать письмо позже, чем
    составил, и потому что ПОДДЕЛКА выглядит ровно так же: кто угодно ставит
    своё клеймо на переписанный текст. Именно поэтому решающей проверкой здесь
    остаётся не подпись, а привязка к двум цепям: подделыватель перепишет
    `issuer` и подпишет своим ключом, но `parties` в чужих журналах не
    перепишет.
    """
    stamped = replace(credential, key_id=key_id(key))
    return replace(stamped, signature=_sign(stamped.signed_body(), key))


# ────────────────────────────────────────────────────────────────────────────
# Проверка предъявленного письма
# ────────────────────────────────────────────────────────────────────────────


def verify(
    credential: Credential,
    ledgers: Mapping[str, Ledger],
    *,
    key: str | bytes | None = None,
    require_signature: bool = True,
    require_ref: bool = True,
) -> tuple[bool, list[str]]:
    """Проверить предъявленное свидетельство. Возвращает (годно, причины).

    Причины — список человекочитаемых строк; у годного письма он пуст. Они
    намеренно не коды: письмо предъявляют человеку, и отказ «цепь заказчика
    нарушена» он может проверить сам, а код ошибки — нет.

    Три случая разделены, потому что означают разное:

      цепь подделана        → доказательства нет ни у кого (ошибка хранения
                              или попытка переписать историю);
      обязательства нет     → письмо выдано под работу, которой не было;
      issuer подменён       → работа была, но хвалит её не её заказчик.

    Про `key`: это HMAC (см. оговорку в начале модуля). Без ключа подпись не
    проверяется, и при `require_signature=True` письмо считается НЕ полностью
    проверенным — но причина так и называется, и вместе с ней сообщается, что
    сама работа при этом доказана цепями.
    """
    ok, reasons = work_proven(credential, ledgers, require_ref=require_ref)
    reasons = list(reasons)

    if not credential.signature:
        if require_signature:
            reasons.append("свидетельство не подписано: клейма мастера нет")
    elif key is None:
        if require_signature:
            reasons.append(
                "подпись не проверена: HMAC-SHA256 — симметричная схема, "
                "для проверки нужен тот же секрет, что у issuer "
                "(работа при этом доказана цепями независимо от подписи)")
    else:
        if credential.alg != ALG_HMAC:
            reasons.append(f"неизвестный алгоритм подписи: {credential.alg!r}")
        elif not credential.signed_by(key):
            reasons.append("подпись не сходится: содержимое изменено либо ключ чужой")
        elif credential.key_id and credential.key_id != key_id(key):
            reasons.append("отпечаток ключа не совпадает с объявленным key_id")

    return (not reasons), reasons


# ────────────────────────────────────────────────────────────────────────────
# Портфолио: то, что исполнитель уносит с собой
# ────────────────────────────────────────────────────────────────────────────


@dataclass
class Portfolio:
    """Набор свидетельств одного исполнителя — цеховая папка, а не рейтинг.

    Папка принимает любое письмо, в том числе чужое и поддельное: исполнитель
    не властен над тем, что ему предъявляют. Разделение на проверяемое и
    непроверяемое делает не сложение, а `verifiable()` — и только по нему
    считается сводка. Иначе среднее по папке было бы теми же звёздочками:
    число, в которое верят, потому что его напечатали.
    """

    subject: str
    credentials: list[Credential] = field(default_factory=list)

    def add(self, credential: Credential) -> "Portfolio":
        self.credentials.append(credential)
        return self

    def __len__(self) -> int:
        return len(self.credentials)

    def __iter__(self) -> Iterator[Credential]:
        return iter(self.credentials)

    @staticmethod
    def collect(subject: str, credentials: Iterable[Credential]) -> "Portfolio":
        """Собрать папку из предъявленных писем, оставив только адресованные subject."""
        return Portfolio(subject, [c for c in credentials if c.subject == subject])

    # ---------- главное: что здесь проверяемо ----------

    def verifiable(
        self,
        ledgers: Mapping[str, Ledger],
        keys: Mapping[str, str | bytes] | None = None,
        *,
        require_signature: bool = True,
    ) -> tuple[list[Credential], list[tuple[Credential, list[str]]]]:
        """Разделить папку: (проверяемые, [(непроверяемое, причины)]).

        `keys` — секреты issuer-ов, какие у проверяющего есть (issuer → ключ).
        Чьего ключа нет, то письмо при `require_signature=True` попадёт в
        непроверяемые с причиной про симметричную схему. Это не придирка:
        именно так и выглядит предел HMAC, и прятать его в «годно» нельзя.
        """
        keys = dict(keys or {})
        good: list[Credential] = []
        bad: list[tuple[Credential, list[str]]] = []
        for cred in self.credentials:
            if cred.subject != self.subject:
                bad.append((cred, [f"письмо адресовано не '{self.subject}', "
                                   f"а '{cred.subject}'"]))
                continue
            ok, reasons = verify(cred, ledgers, key=keys.get(cred.issuer),
                                 require_signature=require_signature)
            if ok:
                good.append(cred)
            else:
                bad.append((cred, reasons))
        return good, bad

    # ---------- сводка ----------

    def summary(
        self,
        ledgers: Mapping[str, Ledger] | None = None,
        keys: Mapping[str, str | bytes] | None = None,
        *,
        require_signature: bool = True,
    ) -> dict[str, Any]:
        """Сводка по папке: сколько работ, средняя оценка, с кем.

        Без `ledgers` сводка считается по ЗАЯВЛЕННОМУ и так и помечается
        (`basis="заявленное"`) — чтобы ни один вызывающий не принял сумму
        непроверенных писем за репутацию. С журналами — только по проверяемым
        (`basis="проверенное"`), а отвергнутые считаются отдельным числом.

        Работы считаются по `commitment_id`, а не по письмам: два письма об
        одной работе — одна работа. Иначе репутацию можно было бы надуть,
        попросив заказчика написать ещё одно письмо о том же.
        """
        if ledgers is None:
            basis, counted, rejected = "заявленное", list(self.credentials), []
        else:
            basis = "проверенное"
            counted, rejected = self.verifiable(ledgers, keys,
                                                require_signature=require_signature)

        works = sorted({c.commitment_id for c in counted})
        ratings_by_work: dict[str, int] = {}
        for c in counted:
            # Если об одной работе два письма, берём худшую оценку: письмо,
            # дописанное позже, не должно улучшать историю.
            prev = ratings_by_work.get(c.commitment_id)
            ratings_by_work[c.commitment_id] = c.rating if prev is None else min(prev, c.rating)

        by_issuer: dict[str, dict[str, Any]] = {}
        for c in counted:
            slot = by_issuer.setdefault(c.issuer, {"works": set(), "ratings": []})
            slot["works"].add(c.commitment_id)
            slot["ratings"].append(c.rating)

        avg = (round(sum(ratings_by_work.values()) / len(ratings_by_work), 2)
               if ratings_by_work else None)

        return {
            "subject": self.subject,
            "basis": basis,
            "credentials": len(counted),
            "works": len(works),
            "average_rating": avg,
            "issuers": sorted(by_issuer),
            "by_issuer": {
                who: {"works": len(d["works"]),
                      "average_rating": round(sum(d["ratings"]) / len(d["ratings"]), 2)}
                for who, d in sorted(by_issuer.items())
            },
            "services": sorted({c.service for c in counted if c.service}),
            "signed": sum(1 for c in counted if c.signature),
            "rejected": len(rejected),
            "rejected_reasons": [
                {"commitment_id": c.commitment_id, "issuer": c.issuer, "reasons": rs}
                for c, rs in rejected
            ],
            "note": "репутация — список проверяемых работ, а не число на профиле: "
                    "каждая строка указывает на обязательство в двух независимых цепях",
        }

    def to_json(self) -> str:
        """Папка целиком — переносимый файл: её уносят из цеха вместе с письмами."""
        return _canonical({"subject": self.subject,
                           "credentials": [c.to_dict() for c in self.credentials]})

    @staticmethod
    def from_json(raw: str) -> "Portfolio":
        d = json.loads(raw)
        return Portfolio(str(d.get("subject", "")),
                         [Credential.from_dict(c) for c in d.get("credentials") or []])
