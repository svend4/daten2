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

ПРО ПОДПИСЬ: ТЕПЕРЬ АСИММЕТРИЧНАЯ, И ЭТО МЕНЯЕТ СУТЬ
---------------------------------------------------
Раньше клеймо мастера было HMAC-SHA256 — симметричной схемой, при которой
проверить подпись может только владелец секрета issuer, а кто может проверить,
тот может и подделать. Переносимой репутации при таком клейме не существует.

Теперь подпись — Ed25519 (RFC 8032, реализация `npp_act/crypto/ed25519.py`,
чистый Python, без зависимостей). Секрет остаётся у issuer, ПУБЛИЧНЫЙ ключ
уезжает в самом свидетельстве и публикуется в паспорте, и `verify()` проверяет
подпись, не имея никаких секретов. Это и есть переносимость: третья сторона,
которая никогда не разговаривала ни с сервисом, ни с issuer, проверяет письмо
сама.

ЧЕТЫРЕ УРОВНЯ ДОВЕРИЯ К ПОДПИСИ — ИХ НЕЛЬЗЯ ПУТАТЬ
--------------------------------------------------
Асимметричная подпись не делает любое письмо достоверным, и подменять одно
другим было бы тем же самообманом, от которого ушли:

  `public`   — Ed25519, подпись сошлась с публичным ключом issuer, который
               проверяющий знает НЕЗАВИСИМО от письма (из паспорта). Только это
               и означает «публично проверено»: ни секрета, ни веры письму.
  `declared` — Ed25519, подпись сошлась с ключом, названным В САМОМ ПИСЬМЕ.
               Так проверена целостность текста, но НЕ личность issuer: кто
               угодно может завести свою пару ключей, вписать себя issuer-ом
               настоящего обязательства (хэши-привязки видны в любом честном
               письме) и подписать это своим ключом. Поэтому `declared` —
               не «проверено», а «подписано неизвестно чьим ключом».
  `secret`   — HMAC-SHA256, подпись сошлась с общим секретом. Унаследованная
               схема: проверяется, но не переносится.
  `none`     — подписи нет, не сошлась или алгоритм неизвестен.

Старые свидетельства с `alg="hmac-sha256"` продолжают проверяться — поле `alg`
для этого и было объявлено с самого начала, и форма подписываемого тела
привязана к нему: поле `public_key` входит в тело подписи только у ed25519,
иначе добавление поля задним числом сделало бы недействительными все ранее
выданные письма.

И по-прежнему главное: работу доказывает не подпись, а ДВЕ НЕЗАВИСИМЫЕ
ХЭШ-ЦЕПИ. `work_proven()` проверяет, что обязательство есть в журналах обеих
сторон, цепи целы, issuer и subject — действительно его стороны, а описанная
работа совпадает с предметом обязательства. Подпись добавляет к этому ровно
одно: что письмо написал тот, кто называется issuer. Поэтому подмена issuer
ловится здесь ДВАЖДЫ — подписью (если известен ключ) и записью в цепи (всегда).

ДЛЯ СПЕЦИФИКАЦИИ (готовый абзац, координатору — перенести)
----------------------------------------------------------
    Свидетельство о выполненной работе ДОЛЖНО быть проверяемо третьей стороной
    без обращения к issuer, к сервису и к любому секрету. Подпись ДОЛЖНА быть
    асимметричной (Ed25519, RFC 8032); публичный ключ issuer ДОЛЖЕН
    присутствовать в свидетельстве и ДОЛЖЕН публиковаться в паспорте стороны.
    Реализация ОБЯЗАНА различать четыре уровня проверки подписи — `public`
    (ключ известен проверяющему независимо от свидетельства), `declared` (ключ
    взят из самого свидетельства: проверена целостность текста, но не личность
    issuer), `secret` (симметричная унаследованная схема) и `none` — и НЕ
    ДОЛЖНА выдавать `declared` за `public`. Публично проверяемым свидетельство
    СЧИТАЕТСЯ только при уровне `public`. Симметричная подпись (HMAC-SHA256)
    ДОПУСКАЕТСЯ для ранее выданных свидетельств и НЕ СЧИТАЕТСЯ публично
    проверяемой. Доказательством самой работы во всех случаях остаются две
    независимые хэш-цепи сторон, а не подпись.

Зависимостей нет: hmac, hashlib, json из стандартной библиотеки плюс
собственный Ed25519 на чистом Python.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator, Mapping

from .agent import Commitment
from .crypto import ed25519
from .ledger import Ledger, LedgerError

#: Шкала оценки. Пять градаций, как у цеховой записи «похвально — с оговорками»:
#: шире шкала не делает её точнее, зато делает несравнимой между цехами.
RATING_MIN, RATING_MAX = 1, 5

#: Алгоритмы клейма. Строкой и в самом свидетельстве — чтобы предъявленное
#: письмо само говорило, чем оно подписано, а не оставляло это допущением.
ALG_HMAC = "hmac-sha256"
ALG_ED25519 = "ed25519"

#: Уровни проверки подписи, от полного к никакому. Подробно — в заголовке
#: модуля; коротко: только `public` означает «проверено публично».
LEVEL_PUBLIC = "public"
LEVEL_DECLARED = "declared"
LEVEL_SECRET = "secret"
LEVEL_NONE = "none"

#: Объяснения уровней для человека. Живут рядом с кодом, а не в документации,
#: потому что их печатает сводка портфолио — а не только читает разработчик.
LEVELS: dict[str, str] = {
    LEVEL_PUBLIC: "проверено публично: Ed25519, ключ issuer известен "
                  "независимо от свидетельства",
    LEVEL_DECLARED: "подписано ключом из самого свидетельства: проверена "
                    "целостность текста, но не личность issuer",
    LEVEL_SECRET: "проверено с секретом: HMAC-SHA256, симметричная схема — "
                  "кто может проверить, тот может и подделать",
    LEVEL_NONE: "подпись не проверена",
}

#: Метки домена. Без них один и тот же ключ, использованный где-то ещё под
#: HMAC, дал бы совпадающие значения, и подпись свидетельства можно было бы
#: добыть из постороннего протокола. У Ed25519 метка своя — чтобы подпись,
#: снятая с одного вида документа, не подходила к другому.
_SIG_LABEL = b"npp-act/credential/signature/v1\x00"
_KID_LABEL = b"npp-act/credential/key-id/v1"
_ED_LABEL = b"npp-act/credential/ed25519/v1\x00"
_PKID_LABEL = b"npp-act/credential/public-key-id/v1"


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


def public_key_id(public: str | bytes) -> str:
    """Отпечаток ПУБЛИЧНОГО ключа: короткое «как выглядит клеймо».

    В отличие от `key_id()` вычисляется из общедоступного значения, поэтому его
    может посчитать любой — и сверить, что три письма в папке подписаны одним и
    тем же ключом, не спрашивая issuer. Это и есть цеховое клеймо: его узнают,
    а не доверяют на слово.
    """
    raw = ed25519.public_hex(public)
    return "pk_" + hashlib.sha256(_PKID_LABEL + bytes.fromhex(raw)).hexdigest()[:16]


@dataclass(frozen=True)
class SigningKey:
    """Пара ключей issuer: секрет остаётся у мастера, публичный уезжает в письме.

    Отдельным типом, а не просто двумя строками, по двум причинам. Во-первых,
    тип — это и есть способ выбрать алгоритм: `sign(cred, "строка")` остаётся
    унаследованным HMAC, `sign(cred, SigningKey(...))` — Ed25519. Угадывать
    схему по длине ключа было бы ровно тем сортом догадки, из-за которого
    потом неясно, чем подписано письмо.

    Во-вторых, `__repr__` переопределён: приватный ключ не должен попадать в
    логи и трассировки просто потому, что кто-то напечатал объект.
    """

    private: str
    public: str
    alg: str = ALG_ED25519

    @property
    def key_id(self) -> str:
        return public_key_id(self.public)

    def passport_block(self, who: str = "") -> dict[str, Any]:
        """Публичная часть для паспорта стороны. Секрета здесь нет по построению.

        Паспорт — то независимое место, откуда проверяющий берёт ключ, чтобы
        проверка дала уровень `public`, а не `declared`. Поэтому блок содержит
        ровно то, что можно публиковать, и ничего больше.
        """
        block = {"alg": self.alg, "public_key": self.public, "key_id": self.key_id}
        if who:
            block["profile"] = who
        return block

    def __repr__(self) -> str:  # приватный ключ не печатаем
        return f"SigningKey(alg={self.alg!r}, public={self.public!r}, key_id={self.key_id!r})"

    __str__ = __repr__


def new_issuer_key(seed: str | bytes | None = None) -> SigningKey:
    """Создать пару ключей issuer.

    Без `seed` ключ берётся из CSPRNG операционной системы. `seed` принимается
    для воспроизводимых прогонов и для восстановления ключа из сохранённых
    32 байт — публичный ключ при этом получается тот же, так что паспорт не
    приходится хранить второй копией.
    """
    private, public = ed25519.keypair(seed)
    return SigningKey(private=private, public=public)


def _sign(body: dict[str, Any], key: str | bytes) -> str:
    msg = _SIG_LABEL + _canonical(body).encode("utf-8")
    return "hs256:" + hmac.new(_as_bytes(key), msg, hashlib.sha256).hexdigest()


def _ed_message(body: dict[str, Any]) -> bytes:
    return _ED_LABEL + _canonical(body).encode("utf-8")


def _sign_ed(body: dict[str, Any], private: str | bytes) -> str:
    return "ed25519:" + ed25519.sign(_ed_message(body), private).hex()


def _verify_ed(body: dict[str, Any], signature: str, public: str | bytes) -> bool:
    if not signature.startswith("ed25519:"):
        return False
    return ed25519.verify(_ed_message(body), signature[len("ed25519:"):], public)


def _key_meta(key: "SigningKey | str | bytes | None") -> tuple[str, str, str]:
    """(алгоритм, key_id, публичный ключ) по тому, чем собираются подписывать."""
    if key is None:
        return ALG_HMAC, "", ""
    if isinstance(key, SigningKey):
        return ALG_ED25519, key.key_id, key.public
    return ALG_HMAC, key_id(key), ""


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
    #: Публичный ключ issuer (hex, 32 байта) — то, из-за чего письмо вообще
    #: переносимо: получатель проверяет подпись, ничего ни у кого не спрашивая.
    #: Пусто у унаследованных писем с alg="hmac-sha256".
    public_key: str = ""
    signature: str = ""

    # ---------- форма для подписи и переноса ----------

    def signed_body(self) -> dict[str, Any]:
        """Всё, что покрыто подписью: само письмо без самой подписи.

        Состав тела зависит от `alg`, и это не прихоть: `public_key` появился
        вместе с Ed25519, и если включать его в тело безусловно, то все
        свидетельства, подписанные HMAC до этого, перестали бы проверяться —
        их подпись стоит под телом БЕЗ этого поля. Поэтому поле входит в тело
        только у схемы, вместе с которой оно появилось.
        """
        body = {
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
        if self.alg != ALG_HMAC:
            body["public_key"] = self.public_key
        return body

    def to_dict(self) -> dict[str, Any]:
        d = self.signed_body()
        # Публичный ключ есть в переносимой форме всегда, когда он есть:
        # получателю он нужен, даже если тело подписи его не покрывает.
        if self.public_key:
            d["public_key"] = self.public_key
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
            public_key=str(d.get("public_key", "")),
            signature=str(d.get("signature", "")),
        )

    @staticmethod
    def from_json(raw: str) -> "Credential":
        return Credential.from_dict(json.loads(raw))

    # ---------- мелочи ----------

    @property
    def parties(self) -> list[str]:
        return sorted(self.anchors)

    def signed_by(self, key: "SigningKey | str | bytes") -> bool:
        """Сходится ли клеймо с этим ключом.

        Что считать ключом, решает объявленный в письме `alg`, а не догадка по
        длине: у `ed25519` это ПУБЛИЧНЫЙ ключ issuer (секрет для проверки не
        нужен — в этом весь смысл), у `hmac-sha256` — общий секрет. Сравнение
        HMAC идёт через `compare_digest`, чтобы по времени сравнения нельзя
        было подбирать подпись побайтово.
        """
        if not self.signature:
            return False
        if self.alg == ALG_ED25519:
            public = key.public if isinstance(key, SigningKey) else key
            return _verify_ed(self.signed_body(), self.signature, public)
        if self.alg == ALG_HMAC:
            if isinstance(key, SigningKey):
                return False  # ed25519-пара к симметричной подписи не подходит
            return hmac.compare_digest(self.signature, _sign(self.signed_body(), key))
        return False

    def self_consistent(self) -> bool:
        """Сходится ли подпись с ключом, названным В САМОМ письме.

        Отдельным методом — чтобы в коде было видно, что это НЕ проверка
        личности issuer: ключ взят оттуда же, откуда текст. Проверяется только
        одно — что после подписания письмо не правили. Для `hmac-sha256`
        бессмысленно и возвращает False: симметричный секрет в письме не ездит.
        """
        if self.alg != ALG_ED25519 or not self.public_key:
            return False
        return self.signed_by(self.public_key)

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
    key: "SigningKey | str | bytes | None" = None,
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

    `key` — клеймо issuer. `SigningKey` (пара Ed25519) даёт переносимое письмо:
    публичный ключ уезжает в нём, и проверить подпись сможет кто угодно.
    Строка или байты означают унаследованный HMAC и оставлены для совместимости
    с уже выданными письмами. Без ключа письмо выдаётся неподписанным: это не
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

    alg, kid, public = _key_meta(key)
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
        alg=alg,
        key_id=kid,
        public_key=public,
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


def sign(credential: Credential, key: "SigningKey | str | bytes") -> Credential:
    """Поставить клеймо на письмо (или переставить его другим ключом).

    Отдельной функцией — потому что мастер может подписать письмо позже, чем
    составил, и потому что ПОДДЕЛКА выглядит ровно так же: кто угодно ставит
    своё клеймо на переписанный текст. Асимметричная подпись этого не отменяет:
    подделыватель заводит свою пару ключей, вписывает себя issuer-ом и
    подписывает — подпись сойдётся с его же публичным ключом. Отвергает такое
    письмо не подпись, а две вещи: привязка к двум чужим цепям (`parties` в
    них не перепишешь) и несовпадение ключа с тем, который issuer опубликовал
    в паспорте.

    Алгоритм выбирается типом ключа: `SigningKey` → Ed25519, строка или
    байты → унаследованный HMAC. Объявленный `alg` письма переписывается под
    ключ, иначе письмо утверждало бы одно, а было подписано другим.
    """
    alg, kid, public = _key_meta(key)
    stamped = replace(credential, alg=alg, key_id=kid, public_key=public)
    if isinstance(key, SigningKey):
        return replace(stamped, signature=_sign_ed(stamped.signed_body(), key.private))
    return replace(stamped, signature=_sign(stamped.signed_body(), key))


# ────────────────────────────────────────────────────────────────────────────
# Проверка предъявленного письма
# ────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Verdict:
    """Итог проверки: не только «годно», но и НА КАКОМ ОСНОВАНИИ.

    Нужен потому, что «проверено» бывает четырёх разных сортов (см. заголовок
    модуля), и вызывающий, который видит только `bool`, неизбежно принимает
    слабейший сорт за сильнейший. `level` называет сорт прямо, а `work_proven`
    отделяет доказанность САМОЙ РАБОТЫ от состояния подписи: работа может быть
    доказана цепями, когда подпись проверить нечем, — и наоборот.
    """

    ok: bool
    reasons: list[str]
    work_proven: bool
    level: str
    alg: str
    key_id: str
    public_key: str

    @property
    def public(self) -> bool:
        """Проверено публично: без секретов и без веры самому письму."""
        return self.level == LEVEL_PUBLIC

    def explain(self) -> str:
        head = "годно" if self.ok else "не годно"
        return (f"{head}: работа {'доказана' if self.work_proven else 'не доказана'}, "
                f"подпись — {LEVELS.get(self.level, self.level)}"
                + ("; " + "; ".join(self.reasons) if self.reasons else ""))


def _check_signature(
    credential: Credential,
    key: "SigningKey | str | bytes | None",
    public_key: str | bytes | None,
) -> tuple[str, list[str], list[str]]:
    """(уровень, жёсткие причины, мягкие причины).

    Разделение причин на две группы повторяет различие, которое есть и в жизни:

      жёсткие — что-то НЕ СОШЛОСЬ (подпись не та, ключ не тот, алгоритм
                неизвестен). Это приговор независимо от того, требовали ли
                подпись: предъявили клеймо, и оно оказалось чужим.
      мягкие  — проверить НЕ ПОЛУЧИЛОСЬ (подписи нет, ключа нет, ключ взят из
                самого письма). Это не обвинение, а состояние, и учитывается
                оно только при `require_signature=True`.
    """
    if not credential.signature:
        return LEVEL_NONE, [], ["свидетельство не подписано: клейма мастера нет"]

    if credential.alg == ALG_ED25519:
        presented = public_key if public_key is not None else key
        if isinstance(presented, SigningKey):
            presented = presented.public
        embedded = credential.public_key

        if presented is None and not embedded:
            return LEVEL_NONE, [], [
                "в свидетельстве не назван публичный ключ issuer, и проверяющий "
                "своего не предъявил — проверять подпись нечем"]

        # Оба ключа приводятся к одной форме в try: на вход проверки по
        # определению попадают данные от того, кто мог их подделать, и
        # исключение здесь означало бы «проверка упала» вместо «письмо негодно».
        material: str | bytes = presented if presented is not None else embedded
        try:
            normalized = ed25519.public_hex(material)
        except ed25519.Ed25519Error as e:
            return LEVEL_NONE, [f"предъявленный публичный ключ не читается: {e}"], []

        if presented is not None and embedded:
            try:
                embedded_hex = ed25519.public_hex(embedded)
            except ed25519.Ed25519Error as e:
                return LEVEL_NONE, [
                    f"публичный ключ в самом свидетельстве не читается: {e}"], []
            if normalized != embedded_hex:
                return LEVEL_NONE, [
                    "предъявленный публичный ключ issuer не тот, которым подписано "
                    "свидетельство: письмо подписал не тот, кем оно подписано по "
                    "паспорту issuer"], []
        if not credential.signed_by(normalized):
            return LEVEL_NONE, [
                "подпись не сходится: содержимое изменено либо ключ чужой"], []
        if credential.key_id and credential.key_id != public_key_id(normalized):
            return LEVEL_NONE, ["отпечаток ключа не совпадает с объявленным key_id"], []

        if presented is None:
            # Подпись цела, но ключ взят оттуда же, откуда текст. Называем это
            # вслух: иначе любой, кто видел честное письмо, выпишет себе такое
            # же от имени того же issuer своей парой ключей.
            return LEVEL_DECLARED, [], [
                "публичный ключ взят из самого свидетельства: проверена целостность "
                "текста, но не личность issuer — для публичной проверки нужен ключ "
                "issuer из независимого источника (паспорт стороны)"]
        return LEVEL_PUBLIC, [], []

    if credential.alg == ALG_HMAC:
        if credential.public_key:
            # Поле, которое ничем не покрыто и ничего не доказывает, обязано
            # называться ошибкой: иначе письмо выглядит «с публичным ключом»,
            # а проверить его без секрета всё равно нельзя.
            return LEVEL_NONE, [
                "свидетельство объявлено симметричным (hmac-sha256), но несёт "
                "публичный ключ: это поле подписью не покрыто и ничего не "
                "подтверждает"], []
        if public_key is not None:
            return LEVEL_NONE, [
                f"публичным ключом проверяется только {ALG_ED25519}, а это "
                f"свидетельство подписано {ALG_HMAC} — симметричной схемой"], []
        if key is None:
            return LEVEL_NONE, [], [
                "подпись не проверена: HMAC-SHA256 — симметричная схема, "
                "для проверки нужен тот же секрет, что у issuer "
                "(работа при этом доказана цепями независимо от подписи)"]
        if isinstance(key, SigningKey):
            return LEVEL_NONE, [
                "предъявлена пара ключей Ed25519, а свидетельство подписано "
                "симметричным HMAC — такой ключ к этой подписи не подходит"], []
        if not credential.signed_by(key):
            return LEVEL_NONE, [
                "подпись не сходится: содержимое изменено либо ключ чужой"], []
        if credential.key_id and credential.key_id != key_id(key):
            return LEVEL_NONE, ["отпечаток ключа не совпадает с объявленным key_id"], []
        return LEVEL_SECRET, [], []

    return LEVEL_NONE, [f"неизвестный алгоритм подписи: {credential.alg!r}"], []


def examine(
    credential: Credential,
    ledgers: Mapping[str, Ledger],
    *,
    key: "SigningKey | str | bytes | None" = None,
    public_key: str | bytes | None = None,
    require_signature: bool = True,
    require_ref: bool = True,
) -> Verdict:
    """Полная проверка с названным уровнем доверия к подписи.

    `public_key` — публичный ключ issuer, который проверяющий знает НЕ ИЗ
    ПИСЬМА (из паспорта стороны). Только он даёт уровень `public`: ни секрета,
    ни доверия к самому предъявленному документу при этом не требуется, и
    именно в этом состоял смысл перехода на асимметричную подпись.

    `key` — то же место для унаследованного симметричного секрета; для письма
    с `alg="ed25519"` он читается как публичный ключ, чтобы один словарь
    «что проверяющий знает про каждого issuer» годился для обеих схем.
    """
    work_ok, reasons = work_proven(credential, ledgers, require_ref=require_ref)
    reasons = list(reasons)

    level, hard, soft = _check_signature(credential, key, public_key)
    reasons.extend(hard)
    if require_signature:
        reasons.extend(soft)

    return Verdict(
        ok=not reasons,
        reasons=reasons,
        work_proven=work_ok,
        level=level,
        alg=credential.alg,
        key_id=credential.key_id,
        public_key=credential.public_key,
    )


def verify(
    credential: Credential,
    ledgers: Mapping[str, Ledger],
    *,
    key: "SigningKey | str | bytes | None" = None,
    public_key: str | bytes | None = None,
    require_signature: bool = True,
    require_ref: bool = True,
) -> tuple[bool, list[str]]:
    """Проверить предъявленное свидетельство. Возвращает (годно, причины).

    Причины — список человекочитаемых строк; у годного письма он пуст. Они
    намеренно не коды: письмо предъявляют человеку, и отказ «цепь заказчика
    нарушена» он может проверить сам, а код ошибки — нет.

    Четыре случая разделены, потому что означают разное:

      цепь подделана        → доказательства нет ни у кого (ошибка хранения
                              или попытка переписать историю);
      обязательства нет     → письмо выдано под работу, которой не было;
      issuer подменён       → работа была, но хвалит её не её заказчик;
      ключ не тот           → письмо подписано не тем, кем подписано по
                              паспорту issuer.

    Про ключи: для `alg="ed25519"` достаточно ПУБЛИЧНОГО ключа issuer, никакого
    секрета не требуется — в этом весь смысл. Если ключ не предъявлен вовсе,
    подпись сверяется с ключом, названным в самом письме, и такой результат
    честно считается НЕ полной проверкой (уровень `declared`). Для
    унаследованного `alg="hmac-sha256"` нужен тот же секрет, что у issuer.
    Уровень проверки возвращает `examine()`; здесь он сворачивается в `bool`.
    """
    v = examine(credential, ledgers, key=key, public_key=public_key,
                require_signature=require_signature, require_ref=require_ref)
    return v.ok, v.reasons


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

    def examined(
        self,
        ledgers: Mapping[str, Ledger],
        keys: Mapping[str, str | bytes] | None = None,
        *,
        require_signature: bool = True,
    ) -> list[tuple[Credential, Verdict]]:
        """Каждое письмо со своим вердиктом — основа для всех остальных методов.

        Одно место, где папка проверяется, и три разных взгляда на результат
        (`verifiable`, `publicly_verifiable`, `summary`). Иначе «проверяемо» в
        сводке и «проверяемо» в разделении папки разъехались бы при первой же
        правке — а это ровно тот сорт расхождения, из-за которого потом
        верят числу, которое никто не считал.

        `keys` — то, что проверяющий знает про каждого issuer: публичный ключ
        для писем с `alg="ed25519"`, общий секрет для унаследованных `hmac`.
        Какое из двух — решает объявленный в письме `alg`, а не угадывание.
        """
        known = dict(keys or {})
        out: list[tuple[Credential, Verdict]] = []
        for cred in self.credentials:
            if cred.subject != self.subject:
                out.append((cred, Verdict(
                    ok=False,
                    reasons=[f"письмо адресовано не '{self.subject}', а '{cred.subject}'"],
                    work_proven=False, level=LEVEL_NONE, alg=cred.alg,
                    key_id=cred.key_id, public_key=cred.public_key)))
                continue
            out.append((cred, examine(cred, ledgers, key=known.get(cred.issuer),
                                      require_signature=require_signature)))
        return out

    def verifiable(
        self,
        ledgers: Mapping[str, Ledger],
        keys: Mapping[str, str | bytes] | None = None,
        *,
        require_signature: bool = True,
    ) -> tuple[list[Credential], list[tuple[Credential, list[str]]]]:
        """Разделить папку: (проверяемые, [(непроверяемое, причины)]).

        `keys` — ключи issuer-ов, какие у проверяющего есть (issuer → ключ).
        Чьего ключа нет, то письмо при `require_signature=True` попадёт в
        непроверяемые — но с РАЗНОЙ причиной: у `hmac` это предел симметричной
        схемы (нужен секрет), у `ed25519` — то, что ключ пришлось взять из
        самого письма. Прятать ни то, ни другое в «годно» нельзя.
        """
        good: list[Credential] = []
        bad: list[tuple[Credential, list[str]]] = []
        for cred, v in self.examined(ledgers, keys, require_signature=require_signature):
            (good.append(cred) if v.ok else bad.append((cred, v.reasons)))
        return good, bad

    def publicly_verifiable(
        self,
        ledgers: Mapping[str, Ledger],
        public_keys: Mapping[str, str | bytes] | None = None,
    ) -> tuple[list[Credential], list[tuple[Credential, list[str]]]]:
        """Что в папке проверяемо ПУБЛИЧНО — то есть вообще без секретов.

        Это и есть ответ на вопрос «что из моей репутации я могу унести с
        собой»: письмо попадает сюда только при `alg="ed25519"` И уровне
        `public`, то есть когда подпись сошлась с ключом issuer, известным
        проверяющему независимо от самого письма (из паспорта).

        Унаследованные `hmac`-письма сюда не попадают никогда — даже если
        секрет у проверяющего есть и подпись сошлась. Проверка, для которой
        нужен секрет issuer, непереносима по построению, и считать её публичной
        значило бы снова выдавать желаемое за проверенное.
        """
        good: list[Credential] = []
        bad: list[tuple[Credential, list[str]]] = []
        for cred, v in self.examined(ledgers, public_keys):
            if v.ok and v.public:
                good.append(cred)
                continue
            reasons = list(v.reasons)
            if v.ok and not v.public:
                reasons.append(
                    f"проверено, но не публично: {LEVELS.get(v.level, v.level)}")
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

        Отдельно считается `publicly_verifiable` — сколько из учтённых писем
        проверено БЕЗ СЕКРЕТОВ (уровень `public`). Это и есть «сколько
        репутации переносимо»: остальное проверяется только там, где есть
        секрет issuer, то есть не переносится вместе с исполнителем.
        """
        levels: dict[str, int] = {}
        if ledgers is None:
            basis, counted, rejected = "заявленное", list(self.credentials), []
        else:
            basis = "проверенное"
            counted, rejected = [], []
            for c, v in self.examined(ledgers, keys,
                                      require_signature=require_signature):
                if v.ok:
                    counted.append(c)
                    levels[v.level] = levels.get(v.level, 0) + 1
                else:
                    rejected.append((c, v.reasons))

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
            "algorithms": sorted({c.alg for c in counted if c.signature}),
            "levels": {lv: levels[lv] for lv in sorted(levels)},
            "publicly_verifiable": levels.get(LEVEL_PUBLIC, 0),
            "portable": bool(counted) and levels.get(LEVEL_PUBLIC, 0) == len(counted),
            "key_ids": sorted({c.key_id for c in counted if c.key_id}),
            "rejected": len(rejected),
            "rejected_reasons": [
                {"commitment_id": c.commitment_id, "issuer": c.issuer, "reasons": rs}
                for c, rs in rejected
            ],
            "note": "репутация — список проверяемых работ, а не число на профиле: "
                    "каждая строка указывает на обязательство в двух независимых цепях",
            "levels_note": "publicly_verifiable — сколько писем проверено без всяких "
                           "секретов (Ed25519, ключ issuer из паспорта); остальное "
                           "проверяется только там, где есть секрет issuer, и вместе "
                           "с исполнителем не переносится",
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
