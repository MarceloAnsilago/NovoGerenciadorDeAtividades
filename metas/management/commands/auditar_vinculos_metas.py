from django.core.management.base import BaseCommand
from django.db.models import F, Q
from django.conf import settings

from metas.models import Meta


def _norm(value):
    return (value or "").strip().casefold()


class Command(BaseCommand):
    help = "Audita vinculos de metas com atividades e lista possiveis inconsistencias."

    def add_arguments(self, parser):
        parser.add_argument("--meta-id", type=int, help="Auditar apenas uma meta especifica.")
        parser.add_argument(
            "--include-ok",
            action="store_true",
            help="Inclui metas sem inconsistencias no relatorio.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=500,
            help="Limite maximo de metas processadas (padrao: 500).",
        )
        parser.add_argument(
            "--include-especiais",
            action="store_true",
            help="Inclui metas especiais conhecidas (ex.: expediente sem atividade).",
        )

    def handle(self, *args, **options):
        meta_id = options.get("meta_id")
        include_ok = options.get("include_ok", False)
        include_especiais = options.get("include_especiais", False)
        limit = max(1, int(options.get("limit") or 500))
        meta_expediente_id = getattr(settings, "META_EXPEDIENTE_ID", None)

        qs = Meta.objects.select_related("atividade", "unidade_criadora").order_by("id")
        if meta_id:
            qs = qs.filter(id=meta_id)
        elif meta_expediente_id and not include_especiais:
            qs = qs.exclude(id=meta_expediente_id)

        # Filtro inicial para reduzir volume quando nao for incluir "ok".
        if not include_ok:
            qs = qs.filter(
                Q(atividade__isnull=True)
                | Q(atividade__ativo=False)
                | ~Q(atividade__unidade_origem_id=F("unidade_criadora_id"))
                | ~Q(titulo=F("atividade__titulo"))
            )

        metas = list(qs[:limit])
        if not metas:
            self.stdout.write(self.style.SUCCESS("Nenhuma meta encontrada para os filtros informados."))
            return

        inconsistentes = 0
        self.stdout.write(
            "meta_id | atividade_id | unidade_meta | unidade_atividade | status | motivos | meta_titulo | atividade_titulo"
        )
        for meta in metas:
            atividade = meta.atividade
            motivos = []
            if atividade is None:
                motivos.append("SEM_ATIVIDADE")
            else:
                if not atividade.ativo:
                    motivos.append("ATIVIDADE_INATIVA")
                if atividade.unidade_origem_id != meta.unidade_criadora_id:
                    motivos.append("UNIDADE_DIVERGENTE")
                if _norm(meta.titulo) != _norm(atividade.titulo):
                    motivos.append("TITULO_DIVERGENTE")

            status = "SUSPEITA" if motivos else "OK"
            if motivos:
                inconsistentes += 1
            if include_ok or motivos:
                self.stdout.write(
                    f"{meta.id} | "
                    f"{meta.atividade_id or '-'} | "
                    f"{meta.unidade_criadora_id or '-'} | "
                    f"{(atividade.unidade_origem_id if atividade else '-')} | "
                    f"{status} | "
                    f"{','.join(motivos) if motivos else '-'} | "
                    f"{(meta.titulo or '').strip()} | "
                    f"{((atividade.titulo if atividade else '') or '').strip()}"
                )

        self.stdout.write("")
        self.stdout.write(f"Total analisadas: {len(metas)}")
        self.stdout.write(f"Total suspeitas: {inconsistentes}")
