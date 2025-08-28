from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from datetime import date

@login_required
def calendar_view(request):
    return render(request, 'programar_atividades/calendar.html')

@login_required
def events_feed(request):
    """
    Endpoint simples de eventos no formato FullCalendar.
    Usa os parâmetros GET ?start=YYYY-MM-DD&end=YYYY-MM-DD (ignorados aqui).
    """
    hoje = date.today().isoformat()
    data = [
        {"id": 1, "title": "Evento de teste", "start": hoje},
        # adicione mais se quiser
    ]
    return JsonResponse(data, safe=False)
