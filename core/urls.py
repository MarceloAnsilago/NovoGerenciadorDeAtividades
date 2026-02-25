# core/urls.py
from django.urls import path
from django.views.generic import RedirectView
from . import views

app_name = "core"

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="core:dashboard", permanent=False)),
    path("dashboard/", views.dashboard_view, name="dashboard"),
    path("dashboard/servidor/<int:servidor_id>/", views.dashboard_servidor_view, name="dashboard_servidor"),
    path("admin/dashboard/", views.AdminDashboardView.as_view(), name="admin_dashboard"),
    path(
        "api/dashboard/kpis/",
        views.dashboard_kpis,
        name="dashboard_kpis",
    ),
    path(
        "api/dashboard/metas_por_unidade/",
        views.dashboard_metas_por_unidade,
        name="dashboard_metas_por_unidade",
    ),
    path(
        "api/dashboard/atividades_por_area/",
        views.dashboard_atividades_por_area,
        name="dashboard_atividades_por_area",
    ),
    path(
        "api/dashboard/progresso_mensal/",
        views.dashboard_progresso_mensal,
        name="dashboard_progresso_mensal",
    ),
    path(
        "api/dashboard/programacoes_status_mensal/",
        views.dashboard_programacoes_status_mensal,
        name="dashboard_programacoes_status_mensal",
    ),
    path(
        "api/dashboard/plantao_heatmap/",
        views.dashboard_plantao_heatmap,
        name="dashboard_plantao_heatmap",
    ),
    path(
        "api/dashboard/uso_veiculos/",
        views.dashboard_uso_veiculos,
        name="dashboard_uso_veiculos",
    ),
    path(
        "api/dashboard/top_servidores/",
        views.dashboard_top_servidores,
        name="dashboard_top_servidores",
    ),
    path("estrutura/", views.admin_arvore, name="admin_arvore"),
    path("perfis/", views.perfis, name="perfis"),
    path("perfis/criar/", views.criar_perfil, name="criar_perfil"),
    path("perfis/<int:user_id>/dependencias/", views.perfil_dependencias, name="perfil_dependencias"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),

    # CRUD do jsTree
    path("nos/", views.nos_list, name="nos_list"),
    path("nos/criar/", views.nos_criar, name="nos_criar"),
    path("nos/renomear/<int:pk>/", views.nos_renomear, name="nos_renomear"),
    path("nos/mover/<int:pk>/", views.nos_mover, name="nos_mover"),
    path("nos/<int:pk>/dependencias/", views.nos_dependencias, name="nos_dependencias"),
    path("nos/deletar/<int:pk>/", views.nos_deletar, name="nos_deletar"),

    # Primeiro acesso
    path("primeiro-acesso/", views.primeiro_acesso_token_view, name="primeiro_acesso_token"),
    path("primeiro-acesso/trocar/", views.trocar_senha_primeiro_acesso, name="trocar_senha_primeiro_acesso"),

    # assumir unidade (note o nome do parâmetro: unidade_id)
    path("assumir-unidade/<int:unidade_id>/", views.assumir_unidade, name="assumir_unidade"),

    path("voltar-contexto/", views.voltar_contexto, name="voltar_contexto"),

    path("perfis/<int:user_id>/excluir/", views.excluir_perfil, name="excluir_perfil"),
    path("perfis/<int:user_id>/redefinir-senha/", views.redefinir_senha, name="redefinir_senha"),
]
