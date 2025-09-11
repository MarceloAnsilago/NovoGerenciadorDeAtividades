# programar/views.py
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt

# === Páginas ===
def calendario_view(request):
    return render(request, "programar/calendario.html")

# === APIs “stub” para manter a página funcionando ===
def events_feed(request):
    # FullCalendar feed (vazio por enquanto)
    return JsonResponse([], safe=False)

def metas_disponiveis(request):
    return JsonResponse({"metas": []})

def servidores_para_data(request):
    return JsonResponse({"livres": [], "impedidos": []})

@csrf_exempt
def salvar_programacao(request):
    return JsonResponse({"ok": True, "itens": 0, "servidores_vinculados": 0})

def programacao_do_dia(request):
    return JsonResponse({"ok": True, "programacao": None})

@csrf_exempt
def excluir_programacao(request):
    return JsonResponse({"ok": True})

# === Relatórios (NOVO app) ===
def relatorios_parcial(request):
    start = request.GET.get("start", "")
    end = request.GET.get("end", "")
    html = f"""
    <div id="relatorioPrintArea" class="card border-0 shadow-sm">
      <div class="card-body">
        <h5 class="card-title mb-2">Relatório (parcial)</h5>
        <div class="text-muted">Período: <strong>{start} → {end}</strong></div>
        <p class="mb-0">Stub do app novo — conteúdo real entra na próxima etapa.</p>
      </div>
    </div>
    """
    return JsonResponse({"ok": True, "html": html})

def print_relatorio_semana(request):
    start = request.GET.get("start", "")
    end = request.GET.get("end", "")
    html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Relatório {start} → {end}</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>body{{padding:16px}}</style>
</head>
<body>
  <h3>Relatório semanal (stub)</h3>
  <div class="text-muted">Período: <strong>{start} → {end}</strong></div>
  <div class="alert alert-light border mt-3">Conteúdo real será migrado aqui.</div>
</body>
</html>"""
    return HttpResponse(html)

# (opcional) se seu urls.py expõe isso:
def servidores_por_intervalo(request):
    return JsonResponse({"ok": True, "servidores": []})
