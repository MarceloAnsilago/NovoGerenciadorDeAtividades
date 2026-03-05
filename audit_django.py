#!/usr/bin/env python3
"""
audit_django.py — checklist técnico automático (Django + JS)

O que ele detecta (heurístico, rápido):
- [AUTH] Views em urls.py sem login_required (ou sem permission decorators) — aproximado
- [IDOR] .get(pk=...) / get_object_or_404(..., pk=...) sem filtro de unidade/tenant
- [REDIRECT] redirect(next) / HTTP_REFERER / request.GET['next'] sem validação
- [CSRF] Views POST sem @csrf_protect (heurístico) e/ou usando @csrf_exempt
- [XSS] innerHTML / insertAdjacentHTML / document.write com dados
- [PERF] N+1: aggregate/annotate/filter dentro de loops (heurístico)
- [STYLE] views.py muito grande

Como usar:
  python audit_django.py --root "C:/.../GerenciadorDeAtividades" --app programar

Opcional:
  python audit_django.py --root . --app programar --json report.json
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, Optional


# ----------------------------
# Helpers
# ----------------------------

PY_EXT = {".py"}
TPL_EXT = {".html", ".htm"}
JS_EXT = {".js", ".mjs"}

UNIT_KEYWORDS = {
    "unidade",
    "unidade_id",
    "unidade__id",
    "programacao__unidade",
    "programacao__unidade_id",
    "tenant",
    "org",
    "organization",
    "company",
}

AUTH_DECORATORS = {
    "login_required",
    "permission_required",
    "user_passes_test",
    "staff_member_required",
}

CSRF_DECORATORS = {"csrf_protect", "csrf_exempt"}

@dataclass
class Finding:
    code: str                # e.g., IDOR, AUTH, XSS
    severity: str            # CRITICO, ALTO, MEDIO, BAIXO
    file: str
    line: int
    message: str
    snippet: str | None = None


def read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def iter_files(root: Path, exts: set[str]) -> Iterable[Path]:
    for base, dirs, files in os.walk(root):
        # ignora pastas comuns
        dirs[:] = [d for d in dirs if d not in {".git", ".venv", "venv", "__pycache__", "node_modules", "dist", "build"}]
        for fn in files:
            p = Path(base) / fn
            if p.suffix.lower() in exts:
                yield p


def get_line(text: str, lineno: int) -> str:
    lines = text.splitlines()
    if 1 <= lineno <= len(lines):
        return lines[lineno - 1].rstrip()
    return ""


# ----------------------------
# AST scan for Python
# ----------------------------

class PyScanner(ast.NodeVisitor):
    def __init__(self, file_path: Path, text: str):
        self.file_path = file_path
        self.text = text
        self.findings: list[Finding] = []
        self.current_func: Optional[str] = None
        self.current_decorators: list[str] = []
        self.loop_depth = 0

    def visit_FunctionDef(self, node: ast.FunctionDef):
        prev_func = self.current_func
        prev_decs = self.current_decorators

        self.current_func = node.name
        self.current_decorators = [self._decorator_name(d) for d in node.decorator_list]

        # Heurística: POST/PUT/PATCH/DELETE dentro da view sem csrf_protect e não exempt?
        # (A gente só aponta "suspeito", não garante.)
        has_csrf_protect = any(d in CSRF_DECORATORS for d in self.current_decorators)
        has_auth = any(d in AUTH_DECORATORS for d in self.current_decorators)

        # Aviso de @csrf_exempt
        if "csrf_exempt" in self.current_decorators:
            self._add("CSRF", "ALTO", node.lineno, f"Uso de @csrf_exempt em {node.name} (revise se é necessário).")

        # Aviso de view sem auth (só se parecer view: recebe request e está em views.py)
        if self.file_path.name == "views.py":
            # muitos projetos usam CBV etc; aqui é só aviso.
            if not has_auth:
                self._add("AUTH", "MEDIO", node.lineno, f"Função {node.name} em views.py sem decorator de auth (verifique se deve exigir login/permissão).")

        # Procura redirect inseguro dentro da função
        self.generic_visit(node)

        # Restaura
        self.current_func = prev_func
        self.current_decorators = prev_decs

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        # trata igual
        fn = ast.FunctionDef(
            name=node.name,
            args=node.args,
            body=node.body,
            decorator_list=node.decorator_list,
            returns=node.returns,
            type_comment=node.type_comment,
        )
        fn.lineno = getattr(node, "lineno", 1)
        return self.visit_FunctionDef(fn)

    def visit_For(self, node: ast.For):
        self.loop_depth += 1
        self.generic_visit(node)
        self.loop_depth -= 1

    def visit_While(self, node: ast.While):
        self.loop_depth += 1
        self.generic_visit(node)
        self.loop_depth -= 1

    def visit_Call(self, node: ast.Call):
        # Detecta .get(pk=...) e get_object_or_404(..., pk=...)
        try:
            fn_name = self._call_name(node)
        except Exception:
            fn_name = ""

        # Open redirect / next / referer
        if fn_name.endswith("redirect"):
            # se redirect(arg) e arg vem de GET/POST/META -> suspeito
            if node.args:
                arg_src = self._expr_to_str(node.args[0])
                if any(k in arg_src for k in ["request.GET", "request.POST", "HTTP_REFERER", "request.META", "next"]):
                    self._add("REDIRECT", "CRITICO", node.lineno, f"redirect() com origem do usuário ({arg_src}). Valide com url_has_allowed_host_and_scheme.")
        # Também captura HttpResponseRedirect("..."+next)
        if fn_name.endswith("HttpResponseRedirect") or fn_name.endswith("HttpResponsePermanentRedirect"):
            if node.args:
                arg_src = self._expr_to_str(node.args[0])
                if any(k in arg_src for k in ["request.GET", "request.POST", "HTTP_REFERER", "request.META", "next"]):
                    self._add("REDIRECT", "CRITICO", node.lineno, f"{fn_name} com origem do usuário ({arg_src}). Valide host/scheme.")

        # IDOR: QuerySet.get(pk=...) sem filtro adicional de unidade
        if fn_name.endswith(".get"):
            if self._has_kw(node, "pk") or self._has_kw(node, "id"):
                # Se dentro de uma chamada .get(...), procura se há qualquer filtro de unidade nos kwargs
                if not self._call_has_any_kw_containing(node, UNIT_KEYWORDS):
                    self._add("IDOR", "ALTO", node.lineno, f"Possível IDOR: .get(pk/id=...) sem filtro de unidade/tenant em {self.current_func or 'escopo global'}.")

        if fn_name == "get_object_or_404":
            # Primeiro arg é queryset/model, resto kwargs
            if self._has_kw(node, "pk") or self._has_kw(node, "id"):
                if not self._call_has_any_kw_containing(node, UNIT_KEYWORDS):
                    self._add("IDOR", "ALTO", node.lineno, "Possível IDOR: get_object_or_404(..., pk/id=...) sem escopo de unidade/tenant.")

        # CSRF: procura por @csrf_protect ausente em view com POST (heurístico via comparação de request.method)
        # Aqui detecta uso de request.method == "POST" e se decorators não incluem csrf_protect/exempt.
        if fn_name.endswith("get") or fn_name.endswith("post"):
            pass  # nada

        # N+1 heurístico: aggregate/annotate/filter dentro de loop
        if self.loop_depth > 0 and fn_name.endswith(("aggregate", "count", "exists", "first", "last")):
            self._add("PERF", "MEDIO", node.lineno, f"Possível N+1: chamada {fn_name} dentro de loop.")

        if self.loop_depth > 0 and fn_name.endswith((".filter", ".exclude")):
            # Menos agressivo: filtrar dentro de loop pode ser ok, mas sinaliza.
            self._add("PERF", "BAIXO", node.lineno, f"Possível N+1: {fn_name} dentro de loop (revise).")

        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare):
        # Heurística: if request.method == "POST" e não tem csrf_protect/exempt
        left = self._expr_to_str(node.left)
        comps = [self._expr_to_str(c) for c in node.comparators]
        if "request.method" in left and any('"POST"' in c or "'POST'" in c for c in comps):
            if self.current_func and self.file_path.name == "views.py":
                if not any(d in CSRF_DECORATORS for d in self.current_decorators):
                    self._add("CSRF", "MEDIO", node.lineno, f"View {self.current_func} parece tratar POST sem @csrf_protect (ou @csrf_exempt). Verifique.")
        self.generic_visit(node)

    # ---------- internal ----------
    def _add(self, code: str, severity: str, lineno: int, msg: str):
        self.findings.append(Finding(
            code=code,
            severity=severity,
            file=str(self.file_path),
            line=lineno,
            message=msg,
            snippet=get_line(self.text, lineno),
        ))

    def _decorator_name(self, dec: ast.AST) -> str:
        if isinstance(dec, ast.Name):
            return dec.id
        if isinstance(dec, ast.Attribute):
            return dec.attr
        if isinstance(dec, ast.Call):
            return self._decorator_name(dec.func)
        return ""

    def _call_name(self, node: ast.Call) -> str:
        # returns something like "redirect" or "obj.get" etc
        f = node.func
        if isinstance(f, ast.Name):
            return f.id
        if isinstance(f, ast.Attribute):
            base = self._expr_to_str(f.value)
            return f"{base}.{f.attr}"
        return ""

    def _expr_to_str(self, node: ast.AST) -> str:
        try:
            return ast.unparse(node)  # py3.9+ should work
        except Exception:
            return node.__class__.__name__

    def _has_kw(self, call: ast.Call, key: str) -> bool:
        return any(isinstance(kw, ast.keyword) and kw.arg == key for kw in call.keywords)

    def _call_has_any_kw_containing(self, call: ast.Call, needles: set[str]) -> bool:
        for kw in call.keywords:
            if not isinstance(kw, ast.keyword) or not kw.arg:
                continue
            k = kw.arg.lower()
            if any(n in k for n in needles):
                return True
        return False


# ----------------------------
# JS/Template scan
# ----------------------------

XSS_PATTERNS = [
    (re.compile(r"\.innerHTML\s*="), "CRITICO", "Uso de innerHTML (risco de DOM XSS). Prefira textContent/createElement."),
    (re.compile(r"insertAdjacentHTML\s*\("), "CRITICO", "Uso de insertAdjacentHTML (risco de DOM XSS)."),
    (re.compile(r"\bdocument\.write\s*\("), "ALTO", "Uso de document.write (risco XSS e problemas de performance)."),
]

REDIRECT_PATTERNS = [
    (re.compile(r"redirect\s*\(\s*request\.(GET|POST)\.get\(['\"]next['\"]", re.I), "CRITICO", "redirect usando next direto (open redirect)."),
]

def scan_js_like(file_path: Path, text: str) -> list[Finding]:
    findings: list[Finding] = []
    lines = text.splitlines()
    for idx, line in enumerate(lines, start=1):
        for rx, sev, msg in XSS_PATTERNS:
            if rx.search(line):
                findings.append(Finding("XSS", sev, str(file_path), idx, msg, line.strip()))
        # alguns redirects em templates python, mas pode aparecer em html via template tags
    return findings


# ----------------------------
# urls.py inventory (basic)
# ----------------------------

URL_PATTERN_RX = re.compile(r"path\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*([a-zA-Z0-9_\.]+)")

def scan_urls(file_path: Path, text: str) -> list[Finding]:
    # Apenas inventário simples + alertas básicos
    findings: list[Finding] = []
    for m in URL_PATTERN_RX.finditer(text):
        route = m.group(1)
        view = m.group(2)
        # Se for API e não tem "login" no nome, só sinaliza como BAIXO (heurístico)
        if route.startswith("api/") and "login" not in view.lower():
            findings.append(Finding(
                "ROUTE",
                "BAIXO",
                str(file_path),
                text[:m.start()].count("\n") + 1,
                f"Rota API encontrada: '{route}' -> {view}. Verifique auth/permissions.",
                snippet=m.group(0),
            ))
    return findings


# ----------------------------
# Main
# ----------------------------

def severity_rank(sev: str) -> int:
    order = {"CRITICO": 0, "ALTO": 1, "MEDIO": 2, "BAIXO": 3}
    return order.get(sev.upper(), 9)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="Pasta raiz do projeto (onde está manage.py / apps).")
    ap.add_argument("--app", default="programar", help="Nome do app alvo (pasta). Default: programar")
    ap.add_argument("--json", default=None, help="Salvar relatório em JSON neste caminho.")
    ap.add_argument("--max", type=int, default=300, help="Máximo de achados exibidos no console.")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    app = args.app

    findings: list[Finding] = []

    # 1) Python: foca em app e settings/urls gerais
    py_targets = [
        root / app,
        root / "config",
        root,  # para urls.py na raiz, se existir
    ]

    for base in py_targets:
        if not base.exists():
            continue
        for p in iter_files(base, PY_EXT):
            txt = read_text(p)
            if not txt.strip():
                continue

            # alerta: views.py muito grande
            if p.name == "views.py":
                nlines = txt.count("\n") + 1
                if nlines > 900:
                    findings.append(Finding(
                        "STYLE",
                        "MEDIO",
                        str(p),
                        1,
                        f"views.py muito grande ({nlines} linhas). Considere dividir em módulos e usar services.",
                        snippet=None,
                    ))

            # urls.py inventário
            if p.name == "urls.py":
                findings.extend(scan_urls(p, txt))

            # AST scan python
            try:
                tree = ast.parse(txt)
                sc = PyScanner(p, txt)
                sc.visit(tree)
                findings.extend(sc.findings)
            except SyntaxError:
                findings.append(Finding("PARSE", "BAIXO", str(p), 1, "Falha ao parsear arquivo (SyntaxError).", None))

    # 2) Templates/JS: foca no app
    tpl_root = root / app / "templates"
    static_root = root / app / "static"

    for base in [tpl_root, static_root]:
        if not base.exists():
            continue
        for p in iter_files(base, TPL_EXT | JS_EXT):
            txt = read_text(p)
            if not txt.strip():
                continue
            findings.extend(scan_js_like(p, txt))

    # Ordena
    findings.sort(key=lambda f: (severity_rank(f.severity), f.file, f.line))

    # Console report
    print("\n=== AUDITORIA AUTOMÁTICA (heurística) ===")
    print(f"Root: {root}")
    print(f"App:  {app}")
    print(f"Achados: {len(findings)}\n")

    by_sev = {"CRITICO": 0, "ALTO": 0, "MEDIO": 0, "BAIXO": 0}
    for f in findings:
        by_sev[f.severity.upper()] = by_sev.get(f.severity.upper(), 0) + 1

    print("Resumo por severidade:")
    for sev in ["CRITICO", "ALTO", "MEDIO", "BAIXO"]:
        print(f"  - {sev}: {by_sev.get(sev, 0)}")

    print("\nTop achados (limitado):")
    for i, f in enumerate(findings[: args.max], start=1):
        print(f"\n[{i}] [{f.severity}] [{f.code}] {f.file}:{f.line}")
        print(f"    {f.message}")
        if f.snippet:
            print(f"    > {f.snippet}")

    # JSON output
    if args.json:
        out = [asdict(f) for f in findings]
        Path(args.json).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nRelatório JSON salvo em: {args.json}")

    print("\nObservação: isso é um scanner heurístico. Use como checklist e confirme no código.")

if __name__ == "__main__":
    main()
