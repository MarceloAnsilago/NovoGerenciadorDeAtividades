from django.db import connection
from .models import PerfilUsuario

def set_contexto(request, vinculo_id:int):
    request.session["vinculo_id"] = vinculo_id

def get_contexto(request) -> PerfilUsuario | None:
    vid = request.session.get("vinculo_id")
    if not vid: return None
    return (PerfilUsuario.objects
            .select_related("unidade","perfil_politica")
            .filter(pk=vid).first())

def ids_subarvore(unidade_id:int):
    with connection.cursor() as cur:
        cur.execute("""
            WITH RECURSIVE tree AS (
              SELECT id, parent_id FROM organizacao_unidade WHERE id = %s
              UNION ALL
              SELECT u.id, u.parent_id FROM organizacao_unidade u
              JOIN tree t ON u.parent_id = t.id
            )
            SELECT id FROM tree;
        """, [unidade_id])
        return [row[0] for row in cur.fetchall()]
