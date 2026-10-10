"""Expose the actual versioned card/event contracts without changing legacy specs."""
import json
from pathlib import Path
from fastapi.openapi.utils import get_openapi


def install_contracts(app):
    def document():
        if app.openapi_schema:
            return app.openapi_schema
        data=get_openapi(title=app.title,version=app.version,routes=app.routes)
        schemas=data.setdefault('components',{}).setdefault('schemas',{})
        for name,file in [('SpikeCard','spike_card.v1.0.2.schema.json'),('EpisodeEvent','episode_event.v1.0.2.schema.json')]:
            schemas[name]=json.loads((Path(__file__).parent/file).read_text())
        ref={'$ref':'#/components/schemas/SpikeCard'}
        data['paths']['/api/v1/radar']['get']['responses']['200']['content']['application/json']['schema']={
            'type':'object','properties':{key:{'type':'array','items':ref} for key in ['top_cards','all_cards','historical_cards','risk_cards']}}
        data['paths']['/api/v1/events/stream']['get']['description']='SSE episode data uses EpisodeEvent; replay never authorizes an OS alert. REVERSAL_OBSERVED updates the same episode; diagnostics without an episode are available from /scenario-diagnostics.'
        app.openapi_schema=data
        return data
    app.openapi=document
