"""Structured diagnostics: one record feeds the in-game panel, the copyable
summary/report and the technical log, so they cannot disagree.

Codes are stable. A code names a PROBLEM, never an action: a later version
may handle NPVM-WK-APP-001 differently (the `action` field changes), but the
code keeps meaning "WolvenKit could not read the appearance resource of an
optional piece". Never reuse or repurpose a code; add a new one instead.
tests/diagnostic_codes.json freezes the registry.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import i18n

NPV_VERSION = "0.5.0"
SEVERITIES = ("INFO", "WARNING", "ERROR", "FATAL")

# code: (severity, stage, user text)
CODES = {
    "NPVM-WK-APP-001": ("WARNING", "appearance_conversion",
                        "O WolvenKit nao conseguiu ler o arquivo desta peca."),
    "NPVM-WK-APP-002": ("FATAL", "appearance_conversion",
                        "O WolvenKit nao conseguiu ler um arquivo obrigatorio do corpo ou da cabeca."),
    "NPVM-WK-RES-001": ("INFO", "appearance_conversion",
                        "O WolvenKit nao conseguiu ler uma malha desta peca; a peca manteve a aparencia original."),
    "NPVM-WK-CLI-001": ("FATAL", "conversion",
                        "O WolvenKit falhou durante a conversao."),
    "NPVM-RESOURCE-001": ("WARNING", "appearance_conversion",
                          "O arquivo desta peca nao existe em nenhum mod instalado."),
    "NPVM-RESOURCE-002": ("FATAL", "appearance_conversion",
                          "Falta um arquivo obrigatorio do corpo ou da cabeca."),
    "NPVM-RESOURCE-003": ("INFO", "appearance_conversion",
                          "O mod nao traz uma malha desta peca; ela ficou como no V."),
    "NPVM-APPEAR-001": ("WARNING", "appearance_conversion",
                        "A escolha feita nao existe no arquivo desta peca."),
    "NPVM-APPEAR-002": ("FATAL", "appearance_conversion",
                        "A escolha feita nao existe no arquivo obrigatorio do corpo ou da cabeca."),
    "NPVM-APPEAR-003": ("INFO", "appearance_conversion",
                        "O subtom de pele escolhido nao existe nesta peca; foi usado o tom-base."),
    "NPVM-APPEAR-004": ("INFO", "appearance_conversion",
                        "Parte desta peca nao tem a cor escolhida e manteve a aparencia original."),
    "NPVM-APPEAR-005": ("INFO", "appearance_conversion",
                        "A cor de cilios do editor esta fora da lista; o NPV usa a primeira cor do jogo."),
    "NPVM-APPEAR-006": ("INFO", "appearance_conversion",
                        "A roupa padrao cobre a genitalia; o NPV sai sem ela, como o V vestido."),
    "NPVM-CONVERT-001": ("WARNING", "appearance_conversion",
                         "Esta peca nao pode ser convertida."),
    "NPVM-CONVERT-002": ("FATAL", "appearance_conversion",
                         "Uma peca obrigatoria do corpo ou da cabeca nao pode ser convertida."),
    "NPVM-BAKE-001": ("FATAL", "morph_bake",
                      "As formas do rosto ou do corpo nao puderam ser aplicadas."),
    "NPVM-BAKE-002": ("WARNING", "morph_bake",
                      "As formas do rosto ou do corpo nao puderam ser aplicadas a esta peca; ela ficou no formato padrao."),
    "NPVM-BAKE-003": ("INFO", "morph_bake",
                      "Esta peca nao e desenhada pelo jogo (nenhum nivel de detalhe) e ficou de fora do NPV."),
    "NPVM-PACK-001": ("FATAL", "pack",
                      "O arquivo do personagem nao pode ser montado."),
    "NPVM-IMPORT-001": ("FATAL", "import",
                        "Um arquivo de outro pacote ocupa o lugar do personagem."),
    "NPVM-IMPORT-002": ("FATAL", "import",
                        "Os arquivos do personagem nao puderam ser gravados no jogo."),
    "NPVM-IMPORT-003": ("ERROR", "import",
                        "Este NPV ja foi importado por outra versao do NPV Maker."),
    "NPVM-DEPENDENCY-001": ("FATAL", "import",
                            "O Companion Expansion nao esta ativo."),
    "NPVM-DEPENDENCY-002": ("INFO", "pack",
                            "Esta peca usa um patch do ArchiveXL de outro mod; o NPV depende desse mod instalado."),
    "NPVM-PATCH-001": ("WARNING", "appearance_conversion",
                       "Um patch do ArchiveXL que acrescenta pecas a esta opcao nao pode ser lido; essas pecas ficaram de fora."),
    "NPVM-PROJECT-001": ("FATAL", "project_validation",
                         "O projeto salvo e invalido."),
    "NPVM-PROJECT-002": ("WARNING", "project_validation",
                         "O editor salvou esta opcao duas vezes com escolhas diferentes; foi usada a primeira."),
    "NPVM-BODY-001": ("INFO", "appearance_conversion",
                      "O corpo foi montado a partir do personagem mostrado no editor."),
    "NPVM-BODY-002": ("WARNING", "appearance_conversion",
                      "Uma peca do corpo vista no editor nao pode ser convertida e ficou de fora."),
    "NPVM-BODY-003": ("WARNING", "appearance_conversion",
                      "O corpo foi montado pelas opcoes do editor, como antes da 0.4.14."),
    "NPVM-RUNTIME-001": ("WARNING", "appearance_conversion",
                         "O editor mostrava pecas que o NPV nao tem; elas podem faltar no jogo."),
    "NPVM-HEAD-001": ("INFO", "appearance_conversion",
                      "Esta peca da cabeca foi montada pelo arquivo que o editor mostrou, nao pelo da opcao."),
    "NPVM-HEAD-002": ("INFO", "appearance_conversion",
                      "O editor mostrou esta peca da cabeca vindo de outro arquivo, mas sem certeza; foi usado o caminho antigo."),
    "NPVM-TEMPLATE-001": ("INFO", "appearance_conversion",
        "A cor escolhida foi montada a partir do modelo do arquivo, como o ArchiveXL faz no jogo."),
    "NPVM-TEMPLATE-002": ("WARNING", "appearance_conversion",
        "A cor montada pelo modelo nao bateu com o que o editor mostrou; foi usado o que o editor mostrou."),
    "NPVM-INTERNAL-001": ("FATAL", "conversion",
                          "Erro inesperado no conversor."),
    "NPVM-STATUS-001": ("WARNING", "status",
                        "O painel nao pode ser atualizado naquele momento; a operacao continuou."),
    "NPVM-SETUP-001": ("FATAL", "setup",
                       "O WolvenKit nao esta pronto; a importacao nao foi iniciada."),
    "NPVM-SETUP-002": ("ERROR", "setup",
                       "O download nao terminou (rede, servidor ou fonte fora das oficiais)."),
    "NPVM-SETUP-003": ("ERROR", "setup",
                       "O arquivo baixado nao confere com o oficial e foi descartado."),
    "NPVM-SETUP-004": ("ERROR", "setup",
                       "O ZIP escolhido nao e o WolvenKit Console 8.19.0 oficial."),
    "NPVM-SETUP-005": ("ERROR", "setup",
                       "Este WolvenKit e de outra versao; o NPV Maker usa so a 8.19.0."),
    "NPVM-SETUP-006": ("ERROR", "setup",
                       "O WolvenKit indicado nao rodou."),
    "NPVM-SETUP-007": ("ERROR", "setup",
                       "Nao ha .NET 8 utilizavel."),
    "NPVM-SETUP-008": ("ERROR", "setup",
                       "A pasta de ferramentas do NPV Maker nao pode ser usada (permissao ou espaco)."),
    "NPVM-SETUP-009": ("WARNING", "setup",
                       "A instalacao do WolvenKit mudou ou esta incompleta."),
    "NPVM-SETUP-010": ("INFO", "setup",
                       "WolvenKit 8.19.0 pronto."),
    "NPVM-REMOVE-001": ("INFO", "removal",
                        "Os arquivos deste NPV foram removidos."),
    "NPVM-REMOVE-002": ("WARNING", "removal",
                        "O jogo esta usando um arquivo deste NPV; ele sera apagado quando o jogo abrir de novo."),
    "NPVM-REMOVE-003": ("WARNING", "removal",
                        "Um arquivo deste NPV foi alterado depois da importacao e nao foi apagado."),
    "NPVM-REMOVE-004": ("ERROR", "removal",
                        "O NPV pedido nao esta na lista de importados."),
    "NPVM-BRIDGE-001": ("WARNING", "bridge",
                        "Um arquivo gravado pelo jogo nao pode ser lido e foi descartado."),
    "NPVM-PACKAGE-001": ("ERROR", "export",
                         "Nao foi possivel criar o pacote deste NPV."),
    "NPVM-PACKAGE-002": ("INFO", "export",
                         "Pacote do NPV criado."),
    "NPVM-PACKAGE-003": ("ERROR", "package_install",
                         "Faltam requisitos para reconstruir este NPV."),
    "NPVM-PACKAGE-004": ("WARNING", "package_install",
                         "Um requisito nao foi conferido ou veio de outro arquivo."),
    "NPVM-PACKAGE-005": ("ERROR", "package_install",
                         "Outra versao deste NPV ja esta instalada."),
    "NPVM-PACKAGE-006": ("ERROR", "package_install",
                         "Pacote NPV invalido ou feito para uma versao mais nova do NPV Maker."),
    "NPVM-PACKAGE-007": ("ERROR", "export",
                         "Esta versao do NPV ja foi exportada."),
    "NPVM-PHOTO-001": ("WARNING", "pack",
                       "Os arquivos do modo foto nao puderam ser gerados; o NPV saiu sem modo foto."),
}

# What the player can do; shown after the message in the panel.
HINTS = {
    "NPVM-WK-APP-002": "Copie o relatorio e envie ao suporte.",
    "NPVM-WK-CLI-001": "Copie o relatorio e envie ao suporte.",
    "NPVM-RESOURCE-002": "Ative os mods de corpo e cabeca usados no V e tente de novo.",
    "NPVM-APPEAR-002": "Ative os mods de corpo e cabeca usados no V e tente de novo.",
    "NPVM-CONVERT-002": "Copie o relatorio e envie ao suporte.",
    "NPVM-BAKE-001": "Copie o relatorio e envie ao suporte.",
    "NPVM-PACK-001": "Copie o relatorio e envie ao suporte.",
    "NPVM-IMPORT-001": "Outro pacote usa o mesmo arquivo. Copie o relatorio e envie ao suporte.",
    "NPVM-IMPORT-002": "Feche outros programas que usem a pasta do jogo e tente de novo.",
    "NPVM-IMPORT-003": "Remova este NPV na aba NPVs, reinicie o jogo e importe de novo.",
    "NPVM-DEPENDENCY-001": "Ative o Companion Expansion e reinicie o jogo antes de importar.",
    "NPVM-PROJECT-001": "Salve o projeto de novo no editor e tente outra vez.",
    "NPVM-INTERNAL-001": "Copie o relatorio e envie ao suporte.",
    "NPVM-SETUP-001": "No editor do NPV maker, use PROXIMO: GERENCIAR > WOLVENKIT.",
    "NPVM-SETUP-002": "Tente de novo ou use INSTALAR ZIP MANUALMENTE.",
    "NPVM-SETUP-003": "Tente baixar de novo.",
    "NPVM-SETUP-004": "Baixe WolvenKit.Console-8.19.0.zip da release 8.19.0 do WolvenKit no GitHub.",
    "NPVM-SETUP-005": "Use BAIXAR AUTOMATICAMENTE para instalar a 8.19.0 sem mexer na sua instalacao.",
    "NPVM-SETUP-006": "Confira o caminho do WolvenKit.CLI.exe ou use BAIXAR AUTOMATICAMENTE.",
    "NPVM-SETUP-007": "Use BAIXAR AUTOMATICAMENTE (baixa o .NET 8 da Microsoft) ou instale o .NET 8.",
    "NPVM-SETUP-008": "Libere espaco ou permissao em %LOCALAPPDATA%\\NPVMaker.",
    "NPVM-SETUP-009": "Instale de novo com um dos botoes da aba WOLVENKIT.",
    "NPVM-RUNTIME-001": "Copie o relatorio e envie ao suporte.",
    "NPVM-REMOVE-002": "Reinicie o jogo; o NPV ja nao aparece depois do reinicio.",
    "NPVM-REMOVE-003": "Confira o arquivo listado no relatorio antes de apagar a mao.",
    "NPVM-PACKAGE-001": "Importe este NPV de novo com esta versao do NPV Maker e tente exportar outra vez.",
    "NPVM-PACKAGE-003": "Instale os requisitos marcados com x, reinicie o jogo e tente de novo.",
    "NPVM-PACKAGE-005": "Remova a versao instalada na aba NPVs, reinicie o jogo e instale de novo.",
    "NPVM-PACKAGE-006": "Baixe o pacote de novo ou atualize o NPV Maker.",
    "NPVM-PACKAGE-007": ("Troque a versao em 1. DADOS (ex.: de 1.0.0 para 1.0.1) e exporte de novo. "
                         "O pacote anterior continua em Documentos\\NPVMaker\\exports."),
}

ACTIONS = {"skipped": "peca ignorada", "kept_captured": "manteve a aparencia original",
           "base_tone": "usou o tom-base", "stopped": "importacao interrompida",
           "external_reference": "referencia ao arquivo original do mod",
           "archivexl_patch": "patch do ArchiveXL aplicado a copia",
           "removed": "removido", "removal_pending": "sera apagado no proximo inicio",
           "kept_modified": "mantido (alterado)", "default_shape": "ficou no formato padrao",
           "first_choice": "usada a primeira escolha",
           "reported": "avisado no relatorio",
           "runtime_origin": "origem vista no editor", "legacy_head": "caminho antigo da cabeca",
           "archivexl_template": "modelo do ArchiveXL", "runtime_preferred": "usado o que o editor mostrou",
           "runtime_body": "corpo do personagem do editor", "legacy_body": "corpo pelas opcoes do editor",
           "exported": "pacote criado", "requirements_checked": "requisitos conferidos"}


def slot_label(option: str, body_part: str = "") -> str:
    name = (option or "").lower()
    for key, label in (("eyelash", "Cilios"), ("eyebrow", "Sobrancelha"), ("brow", "Sobrancelha"),
                       ("hair", "Cabelo"), ("beard", "Barba"), ("eyes", "Olhos"), ("cyberware", "Cyberware"),
                       ("makeup", "Maquiagem"), ("lips", "Maquiagem"), ("piercing", "Piercing"),
                       ("tattoo", "Tatuagem"), ("scar", "Cicatriz"), ("nail", "Unhas"),
                       ("genital", "Genitalia"), ("vagina", "Genitalia"), ("penis", "Genitalia"),
                       ("nipple", "Corpo"), ("breast", "Corpo"), ("body", "Corpo"), ("feet", "Corpo"),
                       ("arms", "Corpo"), ("teeth", "Dentes"), ("skin", "Cabeca"), ("face", "Cabeca"),
                       ("head", "Cabeca")):
        if key in name:
            return label
    return body_part or "Peca"


def redactor(game: Path | None = None):
    """Remove the Windows user and personal folders; keep depot paths.

    Depot paths (base\\..., ep1\\..., mod folders) are relative and pass
    unchanged. Absolute local paths collapse to <JOGO> or <USUARIO>.
    """
    replacements = []
    if game:
        for form in {str(game), str(game).replace("\\", "/"), str(Path(game).resolve())}:
            replacements.append((re.compile(re.escape(form), re.I), "<JOGO>"))
    home = Path.home()
    for form in {str(home), str(home).replace("\\", "/")}:
        replacements.append((re.compile(re.escape(form), re.I), "<USUARIO>"))
    generic = re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/:*?\"<>|\r\n]+", re.I)
    user = os.environ.get("USERNAME") or os.environ.get("USER") or ""

    def clean(text):
        if text is None:
            return None
        text = str(text)
        for pattern, token in replacements:
            text = pattern.sub(token, text)
        text = generic.sub("<USUARIO>", text)
        if len(user) >= 3:
            text = re.sub(r"(?<![A-Za-z0-9])" + re.escape(user) + r"(?![A-Za-z0-9])", "<USUARIO>", text, flags=re.I)
        return text
    return clean


def printable(text):
    """Control characters are shown escaped so copied text stays one block.

    Found with a malformed test capture whose path held a newline and a bell.
    """
    if text is None:
        return None
    return "".join(c if c >= " " else "\\x%02x" % ord(c) for c in str(text))


def make(code: str, *, character: str = "", project: str = "", option: str = "", body_part: str = "",
         selection: str = "", resource: str = "", source_mod: str | None = None, tool: str = "",
         tool_version: str = "", technical_error: str = "", action: str = "", result: str = "",
         external_dependency: dict | None = None, redact=None) -> dict:
    if code not in CODES:
        raise KeyError("Unregistered diagnostic code " + code)
    severity, stage, text = CODES[code]
    base = redact or redactor()

    def clean(value):
        return printable(base(value))
    character, option, selection = printable(character), printable(option), printable(selection)
    source_mod = printable(source_mod)
    technical_error = " | ".join((technical_error or "").splitlines())
    return {"code": code, "severity": severity, "stage": stage, "message": text, "hint": HINTS.get(code, ""),
            "npv_version": NPV_VERSION, "character": character, "project": project,
            "slot": slot_label(option, body_part), "option": option, "selection": selection,
            "resource": clean(resource), "source_mod": source_mod, "tool": tool, "tool_version": tool_version,
            "technical_error": clean((technical_error or "")[:1500]), "action": action,
            "action_text": ACTIONS.get(action, action), "result": result,
            "external_dependency": external_dependency, "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


class DiagnosticError(Exception):
    """A fatal diagnostic raised through the pipeline."""

    def __init__(self, diagnostic: dict):
        super().__init__(diagnostic["code"] + ": " + (diagnostic.get("technical_error") or diagnostic["message"]))
        self.diagnostic = diagnostic


def headline(character: str, diagnostics: list[dict], stage: str, lang: str = i18n.SOURCE) -> str:
    """The panel message; `lang` other than Portuguese is for storage_bridge (i18n)."""
    fatal = [d for d in diagnostics if d["severity"] in ("FATAL", "ERROR")]
    warnings = [d for d in diagnostics if d["severity"] == "WARNING"]
    if stage == "removed":
        if any(d["code"] == "NPVM-REMOVE-002" for d in diagnostics):
            return i18n.text(character + " removido do Companion. Reinicie o jogo para concluir.", lang)
        return i18n.text(character + " removido. Reinicie o jogo.", lang)
    if stage == "error" or fatal:
        first = fatal[0] if fatal else diagnostics[0]
        piece = i18n.slot_text(first["slot"], lang) + ": " if first.get("option") else ""
        failed = {"export": "Exportacao falhou", "package_install": "Instalacao do pacote falhou"}.get(
            first.get("stage"), "Importacao falhou")
        hint = i18n.hint_text(first["code"], lang, first["hint"]) if first.get("hint") else ""
        return (i18n.text(failed, lang) + " (" + first["code"] + "). " + piece
                + i18n.code_text(first["code"], lang, first["message"]) + (" " + hint if hint else ""))
    if warnings:
        return i18n.text(character + " importado com " + str(len(warnings)) + " aviso(s). Reinicie o jogo.", lang)
    # Not every NPV goes to Companion Expansion any more (CRIAR NPV, author 01/10/2026).
    return i18n.text(character + " importado! Reinicie o jogo.", lang)


def line(d: dict, lang: str = i18n.SOURCE) -> str:
    piece = i18n.slot_text(d["slot"], lang) + (" (" + d["selection"] + ")" if d.get("selection") else "")
    return ("- " + piece + ": " + i18n.action_text(d.get("action", ""), lang, d["action_text"])
            + " [" + d["code"] + "]")


def summary(character: str, diagnostics: list[dict], stage: str) -> str:
    """Short text for Nexus/Discord."""
    shown = [d for d in diagnostics if d["severity"] != "INFO"]
    parts = ["NPV Maker " + NPV_VERSION + " - " + headline(character, diagnostics, stage)]
    for d in shown:
        mod = " | mod: " + d["source_mod"] if d.get("source_mod") else ""
        parts.append(line(d) + mod)
    return "\n".join(parts)


FIELDS = ("code", "severity", "stage", "hint", "npv_version", "character", "project", "slot", "option", "selection",
          "resource", "source_mod", "tool", "tool_version", "technical_error", "action", "result",
          "external_dependency", "time")


def report(character: str, diagnostics: list[dict], stage: str) -> str:
    """Every field of every diagnostic, for investigation."""
    blocks = ["NPV Maker " + NPV_VERSION + " - relatorio de diagnostico",
              "resultado: " + headline(character, diagnostics, stage),
              "diagnosticos: " + str(len(diagnostics))]
    for index, d in enumerate(diagnostics, 1):
        blocks.append("")
        blocks.append("[" + str(index) + "] " + d["message"])
        for field in FIELDS:
            value = d.get(field)
            if value in (None, "", []):
                continue
            if isinstance(value, dict):
                value = json.dumps(value, ensure_ascii=False, sort_keys=True)
            blocks.append(field + "=" + str(value).replace("\r", " ").replace("\n", " | "))
    return "\n".join(blocks)


def log_lines(diagnostics: list[dict]) -> list[str]:
    """Technical log: the same records, one JSON object per line."""
    return [json.dumps(d, ensure_ascii=False, sort_keys=True) for d in diagnostics]
