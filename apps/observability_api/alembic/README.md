# Alembic

Migrations próprias da Observability API.

O banco `rubrica_observability` pertence exclusivamente a esta API. A tabela
inicial `observability_records` armazena somente registros internos futuros da
fronteira de observabilidade; ela não duplica logs do Loki e não consulta bancos
de Core, Auth, Notification ou AI.
