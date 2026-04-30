"""Supabase REST client — toda comunicação via API HTTP, sem conexão direta PostgreSQL."""
import structlog
from functools import lru_cache
from supabase import create_client, Client
from agent.config import settings

log = structlog.get_logger(__name__)


@lru_cache(maxsize=1)
def get_supabase() -> Client:
    """Retorna singleton do client Supabase usando service role key."""
    log.info("supabase.client.init", url=settings.supabase_url)
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


# Atalho para uso direto nos módulos
supabase: Client = get_supabase()
