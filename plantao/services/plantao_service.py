from __future__ import annotations

from datetime import date
from typing import Any

from plantao.models import SemanaServidor


def listar_plantonistas_por_data(unidade_id: int, data_ref: date) -> list[dict[str, Any]]:
    qs = (
        SemanaServidor.objects.select_related("servidor", "semana", "semana__plantao")
        .filter(
            semana__inicio__lte=data_ref,
            semana__fim__gte=data_ref,
            servidor__ativo=True,
        )
        .order_by("ordem", "servidor__nome", "id")
    )

    # Prioriza unidade no plantao; fallback para unidade no servidor.
    try:
        qs = qs.filter(semana__plantao__unidade_id=unidade_id)
    except Exception:
        qs = qs.filter(servidor__unidade_id=unidade_id)

    seen: set[int] = set()
    out: list[dict[str, Any]] = []
    for item in qs:
        sid = int(getattr(item, "servidor_id", 0) or 0)
        if not sid or sid in seen:
            continue
        seen.add(sid)

        semana = getattr(item, "semana", None)
        inicio = getattr(semana, "inicio", None)
        fim = getattr(semana, "fim", None)
        periodo = f"{inicio:%d/%m} a {fim:%d/%m}" if inicio and fim else ""

        out.append(
            {
                "id": sid,
                "nome": getattr(getattr(item, "servidor", None), "nome", "") or "",
                "periodo": periodo,
            }
        )
    return out
