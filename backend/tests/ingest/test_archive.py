"""Abertura segura de exports: o que entra, e principalmente o que não entra."""

from __future__ import annotations

import io
import stat
import zipfile
from pathlib import Path

import pytest

from radar.ingest.archive import ArchiveLimits, InvalidExport, UnsafeArchive, open_export
from radar.testing import make_zip

CHAT = "10/01/2024 09:00 - Carla Mendes: Bom dia!\n10/01/2024 09:01 - Roberto Lima: Oi\n"


def _write(tmp_path: Path, name: str, data: bytes | str) -> Path:
    path = tmp_path / name
    path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
    return path


def test_txt_solto(tmp_path: Path):
    path = _write(tmp_path, "upload.bin", CHAT)
    with open_export(path, original_name="Conversa do WhatsApp com Roberto Lima.txt") as bundle:
        assert bundle.chat_text == CHAT
        assert bundle.title == "Roberto Lima"
        assert bundle.media_names == []


def test_txt_utf16_de_aparelho_antigo(tmp_path: Path):
    path = _write(tmp_path, "chat.txt", CHAT.encode("utf-16"))
    with open_export(path) as bundle:
        assert bundle.chat_text == CHAT


def test_zip_do_ios_com_audio(tmp_path: Path):
    data = make_zip(
        {
            "_chat.txt": CHAT,
            "00000002-AUDIO-2024-01-10-09-02-00.opus": b"OggS-audio-falso",
            "00000003-PHOTO-2024-01-10-09-03-00.jpg": b"\xff\xd8jpeg",
        }
    )
    path = _write(tmp_path, "upload.bin", data)
    with open_export(path, original_name="WhatsApp Chat - Roberto Lima.zip") as bundle:
        assert bundle.chat_name == "_chat.txt"
        assert bundle.title == "Roberto Lima"
        assert bundle.audio_names() == ["00000002-AUDIO-2024-01-10-09-02-00.opus"]
        saved = bundle.save_media(
            "00000002-AUDIO-2024-01-10-09-02-00.opus", tmp_path / "media" / "a.opus"
        )
        assert saved.read_bytes() == b"OggS-audio-falso"


def test_zip_do_android_escolhe_o_txt_da_conversa(tmp_path: Path):
    data = make_zip(
        {
            "contrato.txt": "um documento anexado qualquer, bem maior que a conversa " * 50,
            "Conversa do WhatsApp com Roberto Lima.txt": CHAT,
            "PTT-20240110-WA0001.opus": b"OggS",
            "PTT-20240110-WA0001.opus.txt": "transcrição que veio junto",
        }
    )
    path = _write(tmp_path, "upload.bin", data)
    with open_export(path, original_name="qualquer.zip") as bundle:
        assert bundle.chat_text == CHAT
        assert bundle.title == "Roberto Lima"
        assert bundle.read_sidecar("PTT-20240110-WA0001.opus") == "transcrição que veio junto"
        assert bundle.read_sidecar("nao-existe.opus") is None


@pytest.mark.parametrize(
    "name",
    ["../fora.txt", "pasta/../../fora.txt", "/etc/passwd", "C:\\Windows\\win.ini", "..\\fora.txt"],
)
def test_caminho_que_escapa_da_pasta_e_recusado(tmp_path: Path, name: str):
    path = _write(tmp_path, "upload.bin", make_zip({"_chat.txt": CHAT, name: b"x"}))
    with pytest.raises(UnsafeArchive, match="inválido"):
        open_export(path)


def test_zip_bomb_por_taxa_de_compressao(tmp_path: Path):
    bomb = make_zip({"_chat.txt": CHAT, "bomba.opus": b"\x00" * (8 * 1024 * 1024)})
    assert len(bomb) < 64 * 1024  # 8 MB de zeros viram poucos KB
    path = _write(tmp_path, "upload.bin", bomb)
    with pytest.raises(UnsafeArchive, match="zip bomb"):
        open_export(path)


def test_tamanho_total_descompactado_tem_teto(tmp_path: Path):
    import os

    files: dict[str, bytes | str] = {"_chat.txt": CHAT}
    files.update({f"audio{i}.opus": os.urandom(300_000) for i in range(4)})
    path = _write(tmp_path, "upload.bin", make_zip(files))
    with pytest.raises(UnsafeArchive, match="excede"):
        open_export(path, limits=ArchiveLimits(max_uncompressed_bytes=1_000_000))


def test_quantidade_de_arquivos_tem_teto(tmp_path: Path):
    files: dict[str, bytes | str] = {f"a{i}.jpg": b"x" for i in range(30)}
    files["_chat.txt"] = CHAT
    path = _write(tmp_path, "upload.bin", make_zip(files))
    with pytest.raises(UnsafeArchive, match="arquivos demais"):
        open_export(path, limits=ArchiveLimits(max_files=10))


def test_link_simbolico_e_recusado(tmp_path: Path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("_chat.txt", CHAT)
        link = zipfile.ZipInfo("atalho.txt")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, "/etc/passwd")
    path = _write(tmp_path, "upload.bin", buffer.getvalue())
    with pytest.raises(UnsafeArchive, match="links simbólicos"):
        open_export(path)


def test_zip_com_senha_e_recusado(tmp_path: Path):
    # O zipfile do Python não cria zips cifrados; marcamos o bit "cifrado" direto nos cabeçalhos.
    data = bytearray(make_zip({"_chat.txt": CHAT}))
    local = data.index(b"PK\x03\x04")
    central = data.index(b"PK\x01\x02")
    data[local + 6] |= 0x1
    data[central + 8] |= 0x1
    path = _write(tmp_path, "upload.bin", bytes(data))
    with pytest.raises(UnsafeArchive, match="senha"):
        open_export(path)


def test_midia_maior_que_o_limite_nao_e_lida(tmp_path: Path):
    import os

    data = make_zip({"_chat.txt": CHAT, "grande.opus": os.urandom(200_000)})
    path = _write(tmp_path, "upload.bin", data)
    with (
        open_export(path, limits=ArchiveLimits(max_media_bytes=50_000)) as bundle,
        pytest.raises(UnsafeArchive, match="maior"),
    ):
        bundle.read_media("grande.opus")


def test_zip_dentro_do_zip_e_ignorado(tmp_path: Path):
    inner = make_zip({"x.txt": "y"})
    path = _write(tmp_path, "upload.bin", make_zip({"_chat.txt": CHAT, "outro.zip": inner}))
    with open_export(path) as bundle:
        assert bundle.media_names == []


def test_zip_sem_conversa(tmp_path: Path):
    path = _write(tmp_path, "upload.bin", make_zip({"foto.jpg": b"x"}))
    with pytest.raises(InvalidExport, match="não contém"):
        open_export(path)


def test_zip_corrompido(tmp_path: Path):
    path = _write(tmp_path, "upload.bin", b"PK\x03\x04" + b"lixo" * 100)
    with pytest.raises(InvalidExport):
        open_export(path)


def test_binario_que_nao_e_zip_nem_texto(tmp_path: Path):
    path = _write(tmp_path, "upload.bin", b"\x89PNG\r\n\x1a\n" + b"\x00" * 200)
    with pytest.raises(InvalidExport):
        open_export(path)
