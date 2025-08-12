from django.shortcuts import render

def pagina_servidores(request):
    return render(request, "organizacao/stub.html", {"titulo": "Servidores"})

def pagina_veiculos(request):
    return render(request, "organizacao/stub.html", {"titulo": "Veículos"})

def pagina_descanso(request):
    return render(request, "organizacao/stub.html", {"titulo": "Descanso"})

def pagina_plantao(request):
    return render(request, "organizacao/stub.html", {"titulo": "Plantão"})

def pagina_metas(request):
    return render(request, "organizacao/stub.html", {"titulo": "Metas"})
