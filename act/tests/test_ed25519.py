"""Проверка Ed25519 на чистом Python (act/npp_act/crypto/ed25519.py).

ПОЧЕМУ ЭТОТ НАБОР УСТРОЕН ИМЕННО ТАК
------------------------------------
Своя реализация подписи — ровно тот случай, где самосертификация опаснее всего.
«Подписал и сам проверил» проходит зелёным у любой внутренне согласованной
ошибки: достаточно перепутать порядок байтов или метку домена, и модуль будет
безупречно совместим сам с собой и ни с кем больше. Переносимое свидетельство,
подписанное такой подписью, не проверит никто — а тест будет зелёным.

Поэтому эталон здесь только ВНЕШНИЙ, и его два, независимых друг от друга:

  1. ОФИЦИАЛЬНЫЕ ТЕСТ-ВЕКТОРЫ RFC 8032 §7.1 — пять штук, включая пустое
     сообщение и сообщение на 1023 байта, вписаны ниже константами и сверяются
     ПОБАЙТОВО: и публичный ключ из seed, и сама подпись. Это авторитетный
     документ, а не наши ожидания.
  2. БИБЛИОТЕКА `cryptography` (нативная, та же, что стоит за libsodium-подобными
     реализациями). Её `verify` обязана принимать наши подписи, наш `verify` —
     её, а подписи обязаны совпасть побайтово, потому что Ed25519
     детерминирован. Библиотека вызывается ТОЛЬКО В ТЕСТЕ: если в этом
     интерпретаторе она не импортируется (здесь, например, её нативный модуль
     собран под другую версию Python), сверка уходит в отдельный процесс с
     другим интерпретатором — это даже лучше, потому что процессы не делят
     память и подменить эталон изнутри нечем. Если ни один интерпретатор её не
     даёт, часть проверок внятно скипается, и в итоге написано, сколько.

Отдельно проверяется, что В РАНТАЙМЕ этой библиотеки нет: разбором `ast`
(никаких её импортов в исходниках), по тексту кода без комментариев и по
`sys.modules` свежего процесса, который импортировал рантайм-модули.

Запуск:  python3 -m act.tests.test_ed25519
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import time
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from act.npp_act.crypto import ed25519 as ed  # noqa: E402

PASSED = 0
FAILED = 0
SKIPPED: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  ✓ {label}")
    else:
        FAILED += 1
        print(f"  ✗ {label}" + (f" — {detail}" if detail else ""))


def skip(label: str, why: str) -> None:
    SKIPPED.append(f"{label}: {why}")
    print(f"  ∼ ПРОПУЩЕНО {label} — {why}")


# ────────────────────────────────────────────────────────────────────────────
# 1. Официальные тест-векторы RFC 8032 §7.1
#
# Взяты из текста RFC дословно (hex склеен из строк документа). Это ВНЕШНИЙ
# эталон: если наша арифметика разойдётся с RFC хоть в одном байте, сверка
# упадёт здесь, а не на живом свидетельстве через полгода.
# ────────────────────────────────────────────────────────────────────────────

RFC_VECTORS: list[dict[str, str]] = [
    {
        "name": "RFC 8032 §7.1 TEST 1",
        "sk": "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
        "pk": "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
        "msg": "",
        "sig": (
            "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
            "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
        ),
    },
    {
        "name": "RFC 8032 §7.1 TEST 2",
        "sk": "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
        "pk": "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
        "msg": "72",
        "sig": (
            "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
            "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"
        ),
    },
    {
        "name": "RFC 8032 §7.1 TEST 3",
        "sk": "c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
        "pk": "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025",
        "msg": "af82",
        "sig": (
            "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac"
            "18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a"
        ),
    },
    {
        "name": "RFC 8032 §7.1 TEST 1024",
        "sk": "f5e5767cf153319517630f226876b86c8160cc583bc013744c6bf255f5cc0ee5",
        "pk": "278117fc144c72340f67d0f2316e8386ceffbf2b2428c9c51fef7c597f1d426e",
        "msg": (
            "08b8b2b733424243760fe426a4b54908632110a66c2f6591eabd3345e3e4eb98"
            "fa6e264bf09efe12ee50f8f54e9f77b1e355f6c50544e23fb1433ddf73be84d8"
            "79de7c0046dc4996d9e773f4bc9efe5738829adb26c81b37c93a1b270b20329d"
            "658675fc6ea534e0810a4432826bf58c941efb65d57a338bbd2e26640f89ffbc"
            "1a858efcb8550ee3a5e1998bd177e93a7363c344fe6b199ee5d02e82d522c4fe"
            "ba15452f80288a821a579116ec6dad2b3b310da903401aa62100ab5d1a36553e"
            "06203b33890cc9b832f79ef80560ccb9a39ce767967ed628c6ad573cb116dbef"
            "efd75499da96bd68a8a97b928a8bbc103b6621fcde2beca1231d206be6cd9ec7"
            "aff6f6c94fcd7204ed3455c68c83f4a41da4af2b74ef5c53f1d8ac70bdcb7ed1"
            "85ce81bd84359d44254d95629e9855a94a7c1958d1f8ada5d0532ed8a5aa3fb2"
            "d17ba70eb6248e594e1a2297acbbb39d502f1a8c6eb6f1ce22b3de1a1f40cc24"
            "554119a831a9aad6079cad88425de6bde1a9187ebb6092cf67bf2b13fd65f270"
            "88d78b7e883c8759d2c4f5c65adb7553878ad575f9fad878e80a0c9ba63bcbcc"
            "2732e69485bbc9c90bfbd62481d9089beccf80cfe2df16a2cf65bd92dd597b07"
            "07e0917af48bbb75fed413d238f5555a7a569d80c3414a8d0859dc65a46128ba"
            "b27af87a71314f318c782b23ebfe808b82b0ce26401d2e22f04d83d1255dc51a"
            "ddd3b75a2b1ae0784504df543af8969be3ea7082ff7fc9888c144da2af58429e"
            "c96031dbcad3dad9af0dcbaaaf268cb8fcffead94f3c7ca495e056a9b47acdb7"
            "51fb73e666c6c655ade8297297d07ad1ba5e43f1bca32301651339e22904cc8c"
            "42f58c30c04aafdb038dda0847dd988dcda6f3bfd15c4b4c4525004aa06eeff8"
            "ca61783aacec57fb3d1f92b0fe2fd1a85f6724517b65e614ad6808d6f6ee34df"
            "f7310fdc82aebfd904b01e1dc54b2927094b2db68d6f903b68401adebf5a7e08"
            "d78ff4ef5d63653a65040cf9bfd4aca7984a74d37145986780fc0b16ac451649"
            "de6188a7dbdf191f64b5fc5e2ab47b57f7f7276cd419c17a3ca8e1b939ae49e4"
            "88acba6b965610b5480109c8b17b80e1b7b750dfc7598d5d5011fd2dcc5600a3"
            "2ef5b52a1ecc820e308aa342721aac0943bf6686b64b2579376504ccc493d97e"
            "6aed3fb0f9cd71a43dd497f01f17c0e2cb3797aa2a2f256656168e6c496afc5f"
            "b93246f6b1116398a346f1a641f3b041e989f7914f90cc2c7fff357876e506b5"
            "0d334ba77c225bc307ba537152f3f1610e4eafe595f6d9d90d11faa933a15ef1"
            "369546868a7f3a45a96768d40fd9d03412c091c6315cf4fde7cb68606937380d"
            "b2eaaa707b4c4185c32eddcdd306705e4dc1ffc872eeee475a64dfac86aba41c"
            "0618983f8741c5ef68d3a101e8a3b8cac60c905c15fc910840b94c00a0b9d0"
        ),
        "sig": (
            "0aab4c900501b3e24d7cdf4663326a3a87df5e4843b2cbdb67cbf6e460fec350"
            "aa5371b1508f9f4528ecea23c436d94b5e8fcd4f681e30a6ac00a9704a188a03"
        ),
    },
    {
        "name": "RFC 8032 §7.1 TEST SHA(abc)",
        "sk": "833fe62409237b9d62ec77587520911e9a759cec1d19755b7da901b96dca3d42",
        "pk": "ec172b93ad5e563bf4932c70e1245034c35467ef2efd4d64ebf819683467e2bf",
        "msg": (
            "ddaf35a193617abacc417349ae20413112e6fa4e89a97ea20a9eeee64b55d39a"
            "2192992a274fc1a836ba3c23a3feebbd454d4423643ce80e2a9ac94fa54ca49f"
        ),
        "sig": (
            "dc2a4459e7369633a52b1bf277839a00201009a3efbf3ecb69bea2186c26b589"
            "09351fc9ac90b3ecfdfbc7c66431e0303dca179c138ac17ad9bef1177331a704"
        ),
    },
]


def test_rfc_vectors() -> None:
    print("\nОфициальные тест-векторы RFC 8032 §7.1 (внешний эталон):")
    check("в наборе пять векторов RFC", len(RFC_VECTORS) == 5, str(len(RFC_VECTORS)))
    lengths = sorted(len(v["msg"]) // 2 for v in RFC_VECTORS)
    check("среди них есть пустое сообщение и длинное (1023 байта)",
          lengths[0] == 0 and lengths[-1] == 1023, str(lengths))

    for v in RFC_VECTORS:
        name = v["name"]
        seed = bytes.fromhex(v["sk"])
        want_pub = bytes.fromhex(v["pk"])
        msg = bytes.fromhex(v["msg"])
        want_sig = bytes.fromhex(v["sig"])

        private, public = ed.keypair(seed)
        check(f"{name}: публичный ключ выведен из seed побайтово",
              bytes.fromhex(public) == want_pub, public)
        check(f"{name}: приватный ключ — тот же seed",
              bytes.fromhex(private) == seed, private)
        check(f"{name}: подпись совпала с эталоном побайтово ({len(msg)} байт сообщения)",
              ed.sign(msg, seed) == want_sig, ed.sign(msg, seed).hex())
        check(f"{name}: эталонная подпись принимается нашим verify",
              ed.verify(msg, want_sig, want_pub))
        check(f"{name}: public_of даёт тот же публичный ключ",
              ed.public_of(seed) == want_pub.hex())


# ────────────────────────────────────────────────────────────────────────────
# 2. Сверка с библиотекой `cryptography` — второй независимый эталон
# ────────────────────────────────────────────────────────────────────────────

#: Скрипт-эталон. Запускается либо в этом процессе (через exec-эквивалент —
#: прямой импорт), либо отдельным интерпретатором, который библиотеку тянет.
#: Текст один и тот же, чтобы сверка не зависела от того, каким путём пошли.
ORACLE = r'''
import json, sys
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization as ser
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey)
import cryptography

task = json.load(sys.stdin)
msg = bytes.fromhex(task["message"])
pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(task["public"]))


def accepts(sig_hex):
    try:
        pub.verify(bytes.fromhex(sig_hex), msg)
        return True
    except InvalidSignature:
        return False


priv = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(task["seed"]))
json.dump({
    "library": cryptography.__version__,
    "accepts_ours": accepts(task["our_sig"]),
    "accepts_forgery": accepts(task["bad_sig"]),
    "accepts_malleable": accepts(task["malleable_sig"]),
    "their_public": priv.public_key().public_bytes(
        ser.Encoding.Raw, ser.PublicFormat.Raw).hex(),
    "their_sig": priv.sign(msg).hex(),
}, sys.stdout)
'''


def oracle_inprocess(task: dict) -> dict | None:
    """Попытаться сверяться с библиотекой в ЭТОМ процессе.

    stderr на время импорта уводится в /dev/null дескриптором, а не через
    sys.stderr: несовпадение ABI нативного модуля печатает панику из Rust
    напрямую в fd 2, и без этого вывод теста утонул бы в чужом бэктрейсе.
    Исключение ловится как BaseException, потому что та самая паника
    наследуется прямо от неё, а не от Exception.
    """
    devnull = os.open(os.devnull, os.O_WRONLY)
    saved = os.dup(2)
    try:
        os.dup2(devnull, 2)
        try:
            import cryptography  # noqa: F401  (только в тесте!)
            from cryptography.exceptions import InvalidSignature
            from cryptography.hazmat.primitives import serialization as ser
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PrivateKey, Ed25519PublicKey)
        except BaseException:
            return None
    finally:
        os.dup2(saved, 2)
        os.close(saved)
        os.close(devnull)

    msg = bytes.fromhex(task["message"])
    pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(task["public"]))

    def accepts(sig_hex: str) -> bool:
        try:
            pub.verify(bytes.fromhex(sig_hex), msg)
            return True
        except InvalidSignature:
            return False

    priv = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(task["seed"]))
    return {
        "library": cryptography.__version__,
        "where": f"в этом же процессе ({Path(sys.executable).name})",
        "accepts_ours": accepts(task["our_sig"]),
        "accepts_forgery": accepts(task["bad_sig"]),
        "accepts_malleable": accepts(task["malleable_sig"]),
        "their_public": priv.public_key().public_bytes(
            ser.Encoding.Raw, ser.PublicFormat.Raw).hex(),
        "their_sig": priv.sign(msg).hex(),
    }


def interpreters() -> list[str]:
    """Интерпретаторы, которые стоит спросить про библиотеку.

    Своё окружение здесь не допущение: нативный модуль собирается под
    конкретную версию Python, и библиотека, «установленная в системе», может не
    импортироваться именно тем интерпретатором, которым запущены тесты.
    """
    names = ["python3.13", "python3.12", "python3.11", "python3.10", "python3", "pypy3"]
    found: list[str] = []
    for name in names:
        path = shutil.which(name)
        if path and path not in found and path != sys.executable:
            found.append(path)
    return found


def oracle_subprocess(task: dict) -> dict | None:
    """Сверка с библиотекой в отдельном процессе другим интерпретатором.

    `-I` — изоляция: ни PYTHONPATH, ни user-site, ни каталог скрипта в путях.
    Эталон не должен случайно подхватить наш же модуль и сверить нас с нами.
    """
    for interp in interpreters():
        probe = subprocess.run(
            [interp, "-I", "-c", "import cryptography.hazmat.primitives.asymmetric.ed25519"],
            capture_output=True, text=True)
        if probe.returncode != 0:
            continue
        run = subprocess.run([interp, "-I", "-c", ORACLE], input=json.dumps(task),
                             capture_output=True, text=True, timeout=60)
        if run.returncode != 0 or not run.stdout.strip():
            continue
        out = json.loads(run.stdout)
        out["where"] = f"отдельным процессом: {interp}"
        return out
    return None


def test_against_library() -> None:
    print("\nСверка с библиотекой `cryptography` (второй внешний эталон):")
    seed = bytes(range(32))                      # предсказуемый ключ: сверяемся, не секретничаем
    private, public = ed.keypair(seed)
    msg = "свидетельство о работе: вёрстка каталога, 8 часов".encode("utf-8")
    our_sig = ed.sign(msg, private)

    forged = bytearray(our_sig)
    forged[-1] ^= 0x01                           # подделка: один бит в S
    s = int.from_bytes(our_sig[32:], "little")
    malleable = our_sig[:32] + int.to_bytes(s + ed.L, 32, "little")

    task = {
        "seed": seed.hex(), "public": public, "message": msg.hex(),
        "our_sig": our_sig.hex(), "bad_sig": bytes(forged).hex(),
        "malleable_sig": malleable.hex(),
    }

    out = oracle_inprocess(task) or oracle_subprocess(task)
    if out is None:
        why = ("библиотека не импортируется ни одним найденным интерпретатором "
               f"(пробовали: {Path(sys.executable).name}, "
               f"{', '.join(Path(p).name for p in interpreters()) or '—'})")
        for label in ("её verify принимает нашу подпись",
                      "её подпись принимается нашим verify",
                      "подписи совпали побайтово",
                      "публичные ключи из одного seed совпали",
                      "эталон отвергает подделку",
                      "эталон отвергает подпись с S ≥ L"):
            skip(f"сверка с cryptography — {label}", why)
        return

    print(f"    эталон: cryptography {out['library']}, {out['where']}")
    check("сверка с cryptography — её verify принимает нашу подпись",
          out["accepts_ours"] is True)
    check("сверка с cryptography — публичные ключи из одного seed совпали",
          out["their_public"] == public, f"{out['their_public']} ≠ {public}")
    check("сверка с cryptography — её подпись принимается нашим verify",
          ed.verify(msg, out["their_sig"], public), out["their_sig"])
    # Ed25519 детерминирован, поэтому у двух правильных реализаций подписи
    # обязаны совпасть побайтово. Это самая строгая форма сверки из возможных.
    check("сверка с cryptography — подписи совпали побайтово",
          out["their_sig"] == our_sig.hex(), f"{out['their_sig']} ≠ {our_sig.hex()}")
    # Эталон обязан уметь говорить «нет»: иначе он подтвердил бы что угодно, и
    # зелёная сверка не значила бы ничего.
    check("сверка с cryptography — эталон отвергает подделку",
          out["accepts_forgery"] is False)
    check("сверка с cryptography — эталон отвергает подпись с S ≥ L",
          out["accepts_malleable"] is False)


# ────────────────────────────────────────────────────────────────────────────
# 3. В рантайме библиотеки нет
# ────────────────────────────────────────────────────────────────────────────

RUNTIME_FILES = [
    ROOT / "act/npp_act/crypto/ed25519.py",
    ROOT / "act/npp_act/crypto/__init__.py",
    ROOT / "act/npp_act/credential.py",
]

FORBIDDEN = ("cryptography", "nacl", "pysodium", "ecdsa", "pyca")


def code_without_prose(path: Path) -> str:
    """Исходник без комментариев и строковых литералов-документации.

    Разделение нужно по существу. В ЗАГОЛОВКЕ модуля библиотеку назвать
    ОБЯЗАНЫ: честная оговорка «для ценных активов берите libsodium или
    cryptography» — часть требования не преуменьшать ограничения, и запрет на
    это слово в прозе означал бы запрет на честность. А вот в КОДЕ его быть не
    должно, и проверяется именно код.
    """
    out: list[str] = []
    prev_type = tokenize.INDENT
    with path.open("rb") as fh:
        for tok in tokenize.tokenize(fh.readline):
            if tok.type in (tokenize.COMMENT, tokenize.NL):
                continue
            if tok.type == tokenize.STRING and prev_type in (
                    tokenize.INDENT, tokenize.DEDENT, tokenize.NEWLINE, tokenize.ENCODING):
                continue  # docstring: строка-выражение в начале блока
            out.append(tok.string)
            if tok.type not in (tokenize.COMMENT, tokenize.NL):
                prev_type = tok.type
    return " ".join(out)


def imported_modules(path: Path) -> set[str]:
    """Все модули, которые файл импортирует — разбором ast, а не поиском слов.

    Строковый поиск можно обмануть переносом строки или склейкой; дерево
    разбора — нет. Это главная из трёх проверок чистоты рантайма.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_runtime_is_clean() -> None:
    print("\nВ рантайме внешней криптобиблиотеки нет:")
    for path in RUNTIME_FILES:
        rel = path.relative_to(ROOT)
        mods = imported_modules(path)
        dirty = sorted(m for m in mods if m.lower() in FORBIDDEN)
        check(f"{rel}: ни одного импорта внешней криптобиблиотеки (ast)",
              not dirty, str(dirty))
        code = code_without_prose(path).lower()
        found = [w for w in FORBIDDEN if w in code]
        check(f"{rel}: в коде (без комментариев и docstring) нет этих имён",
              not found, str(found))

    ed_mods = imported_modules(ROOT / "act/npp_act/crypto/ed25519.py")
    check("ed25519.py импортирует только hashlib, secrets и base64",
          ed_mods <= {"hashlib", "secrets", "base64", "__future__"}, str(sorted(ed_mods)))

    # Самая прямая проверка: свежий изолированный процесс импортирует рантайм —
    # и смотрит, что в sys.modules библиотеки нет. Статический разбор можно
    # обойти динамическим импортом, а это — нельзя.
    probe = (
        "import sys; sys.path.insert(0, %r);"
        "import act.npp_act.credential as c;"
        "from act.npp_act.crypto import ed25519 as e;"
        "e.sign(b'x', bytes(32));"
        "bad = sorted(m for m in sys.modules if m.split('.')[0].lower() in %r);"
        "print('|'.join(bad))" % (str(ROOT), FORBIDDEN)
    )
    run = subprocess.run([sys.executable, "-I", "-c", probe],
                         capture_output=True, text=True, timeout=120)
    check("рантайм, импортированный в чистом процессе, не загружает библиотеку",
          run.returncode == 0 and run.stdout.strip() == "",
          f"код {run.returncode}, модули '{run.stdout.strip()}', {run.stderr.strip()[-200:]}")


# ────────────────────────────────────────────────────────────────────────────
# 4. Подделка: подписи, сообщения, ключа
# ────────────────────────────────────────────────────────────────────────────


def test_forgery() -> None:
    print("\nПодделка не проходит:")
    private, public = ed.keypair(bytes([0xA5]) * 32)
    other_priv, other_pub = ed.keypair(bytes([0x5A]) * 32)
    msg = b"work accepted: 8 hours"
    sig = ed.sign(msg, private)

    check("своя подпись проверяется своим ключом", ed.verify(msg, sig, public))

    for bit, where in ((0, "в R"), (32 * 8, "в S")):
        broken = bytearray(sig)
        broken[bit // 8] ^= 1 << (bit % 8)
        check(f"подделка подписи ({where}) отвергнута",
              not ed.verify(msg, bytes(broken), public))

    check("подмена сообщения отвергнута (один байт)",
          not ed.verify(b"work accepted: 9 hours", sig, public))
    check("подмена сообщения отвергнута (пустое вместо непустого)",
          not ed.verify(b"", sig, public))
    check("подмена сообщения отвергнута (дописан хвост)",
          not ed.verify(msg + b" ", sig, public))
    check("чужой публичный ключ подпись не подтверждает",
          not ed.verify(msg, sig, other_pub))
    check("чужая подпись не подходит к нашему ключу",
          not ed.verify(msg, ed.sign(msg, other_priv), public))

    s = int.from_bytes(sig[32:], "little")
    check("S ≥ L отвергается (иначе у письма было бы две верных подписи)",
          not ed.verify(msg, sig[:32] + int.to_bytes(s + ed.L, 32, "little"), public))

    check("подпись не той длины отвергнута, а не взорвалась",
          not ed.verify(msg, sig[:63], public))
    check("ключ не той длины отвергнут", not ed.verify(msg, sig, public[:60]))
    check("мусор вместо ключа отвергнут", not ed.verify(msg, sig, "не ключ вовсе"))
    check("нули вместо подписи отвергнуты", not ed.verify(msg, bytes(64), public))
    # 32 байта не обязаны кодировать точку кривой: старший бит — знак x, и для
    # подавляющего большинства y подходящего x просто не существует.
    check("32 байта, не кодирующие точку кривой, отвергнуты как ключ",
          not ed.verify(msg, sig, bytes([0xFF] * 32)))

    check("приватный ключ не выводится из публичного (он просто другой)",
          private != public)
    check("подпись не содержит приватного ключа",
          bytes.fromhex(private) not in sig)


# ────────────────────────────────────────────────────────────────────────────
# 5. Форма ключей, детерминированность, скорость
# ────────────────────────────────────────────────────────────────────────────


def test_shape_and_speed() -> None:
    print("\nФорма ключей, детерминированность, цена операции:")
    private, public = ed.keypair(b"seed-32-bytes-exactly-padded-ok!")
    check("приватный ключ — 32 байта в hex", len(bytes.fromhex(private)) == ed.SEED_SIZE)
    check("публичный ключ — 32 байта в hex", len(bytes.fromhex(public)) == ed.PUBLIC_SIZE)
    sig = ed.sign(b"m", private)
    check("подпись — ровно 64 байта", len(sig) == ed.SIGNATURE_SIZE and isinstance(sig, bytes),
          str(len(sig)))

    check("один и тот же seed даёт ту же пару ключей",
          ed.keypair(b"seed-32-bytes-exactly-padded-ok!") == (private, public))
    check("подпись детерминирована: та же пара (ключ, сообщение) — та же подпись",
          ed.sign(b"m", private) == sig)
    check("разные сообщения — разные подписи", ed.sign(b"n", private) != sig)
    check("без seed ключи каждый раз новые", ed.keypair()[0] != ed.keypair()[0])

    import base64
    check("ключ принимается в hex", ed.verify(b"m", sig, public))
    check("ключ принимается в base64",
          ed.verify(b"m", sig, base64.b64encode(bytes.fromhex(public)).decode()))
    check("ключ принимается в байтах", ed.verify(b"m", sig, bytes.fromhex(public)))
    check("подпись принимается в hex", ed.verify(b"m", sig.hex(), public))
    check("строка-сообщение подписывается как UTF-8",
          ed.verify("мастер", ed.sign("мастер", private), public)
          and ed.verify("мастер".encode("utf-8"), ed.sign("мастер", private), public))
    check("public_hex приводит base64 и hex к одному виду",
          ed.public_hex(base64.b64encode(bytes.fromhex(public)).decode()) == public)

    for bad, what in ((b"too short", "короткий seed"), ("zz" * 32, "не-hex строка"),
                      (12345, "число вместо ключа")):
        try:
            ed.keypair(bad)
            check(f"{what} отвергнут при создании ключа", False, "прошло")
        except ed.Ed25519Error:
            check(f"{what} отвергнут при создании ключа", True)

    # Скорость измеряется, а не обещается: в заголовке модуля стоит порядок
    # величины, и он должен быть взят отсюда, а не из общих слов.
    n = 20
    t0 = time.perf_counter()
    for _ in range(n):
        ed.sign(b"x" * 256, private)
    t1 = time.perf_counter()
    for _ in range(n):
        ed.verify(b"x" * 256, sig, public)
    t2 = time.perf_counter()
    sps, vps = n / (t1 - t0), n / (t2 - t1)
    print(f"    измерено: {sps:.0f} подписей/с, {vps:.0f} проверок/с "
          f"({(t1 - t0) / n * 1000:.1f} мс и {(t2 - t1) / n * 1000:.1f} мс на операцию)")
    # Порог намеренно низкий: тест о том, что реализация пригодна для выдачи
    # свидетельств, а не о производительности машины, где он запущен.
    check("подпись и проверка укладываются в разумное время (≥ 20 операций/с)",
          sps >= 20 and vps >= 20, f"{sps:.0f}/{vps:.0f}")
    check("заявленный в заголовке порядок (~5 мс на операцию) не разошёлся с измеренным",
          0.2 <= (t1 - t0) / n * 1000 <= 200, f"{(t1 - t0) / n * 1000:.1f} мс")


# ────────────────────────────────────────────────────────────────────────────

def main() -> int:
    test_rfc_vectors()
    test_against_library()
    test_runtime_is_clean()
    test_forgery()
    test_shape_and_speed()

    print(f"\n{'─' * 58}")
    if SKIPPED:
        print(f"Пропущено проверок: {len(SKIPPED)}")
        for s in SKIPPED:
            print(f"  ∼ {s}")
    if FAILED:
        print(f"✗ ПРОВАЛЕНО: {FAILED}, пройдено {PASSED}")
        return 1
    print(f"✓ Все проверки пройдены ({PASSED}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
