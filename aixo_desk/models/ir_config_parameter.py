from odoo import api, models


class IrConfigParameter(models.Model):
    _inherit = 'ir.config_parameter'

    def _aixo_clear_rule_cache(self, keys):
        # Record rules read desk settings through res.users computed fields and
        # ir.rule caches the evaluated domain, so a changed setting must drop it.
        if any(key and key.startswith('aixo_desk.') for key in keys):
            self.env.registry.clear_cache()

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        self._aixo_clear_rule_cache(records.mapped('key'))
        return records

    def write(self, vals):
        keys = self.mapped('key') + ([vals['key']] if 'key' in vals else [])
        result = super().write(vals)
        self._aixo_clear_rule_cache(keys)
        return result

    def unlink(self):
        keys = self.mapped('key')
        result = super().unlink()
        self._aixo_clear_rule_cache(keys)
        return result
