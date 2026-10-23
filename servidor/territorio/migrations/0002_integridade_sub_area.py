from django.db import migrations

# Chave composta: a empresa da sub-área é a empresa da fazenda dela, e `fazenda.empresa_id` não muda
# enquanto houver sub-área (a RLS da Fase 4 confia nessas colunas).
CRIAR = """
ALTER TABLE sub_area ADD CONSTRAINT sub_area_fazenda_da_empresa
    FOREIGN KEY (fazenda_id, empresa_id) REFERENCES fazenda (id, empresa_id);

CREATE FUNCTION sub_area_validar() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    p sub_area%ROWTYPE;
BEGIN
    IF TG_OP = 'UPDATE' AND (
        OLD.pai_id IS DISTINCT FROM NEW.pai_id OR OLD.nivel <> NEW.nivel
        OR OLD.fazenda_id <> NEW.fazenda_id OR OLD.empresa_id <> NEW.empresa_id
    ) THEN
        -- Mover nó não recalcula o caminho dos descendentes; nenhuma tarefa pede mover.
        RAISE EXCEPTION 'sub_area: pai, nivel, fazenda e empresa não mudam' USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.pai_id IS NULL THEN
        NEW.caminho := '/';
    ELSE
        SELECT * INTO p FROM sub_area WHERE id = NEW.pai_id;
        IF p.id IS NULL OR p.fazenda_id <> NEW.fazenda_id OR p.nivel <> NEW.nivel - 1 THEN
            RAISE EXCEPTION 'sub_area: pai de outra fazenda ou de nivel incoerente' USING ERRCODE = 'check_violation';
        END IF;
        NEW.caminho := p.caminho || p.id || '/';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER sub_area_validar BEFORE INSERT OR UPDATE ON sub_area
    FOR EACH ROW EXECUTE FUNCTION sub_area_validar();
"""

REMOVER = """
DROP TRIGGER sub_area_validar ON sub_area;
DROP FUNCTION sub_area_validar();
ALTER TABLE sub_area DROP CONSTRAINT sub_area_fazenda_da_empresa;
"""


class Migration(migrations.Migration):
    dependencies = [('territorio', '0001_initial')]
    operations = [migrations.RunSQL(CRIAR, REMOVER)]
