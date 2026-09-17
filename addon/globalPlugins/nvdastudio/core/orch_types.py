from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Tipos base (existentes)
# ---------------------------------------------------------------------------

@dataclass
class StepResult:
	step_id: str
	step_type: str
	output: str
	approved: bool
	score: int
	issues: list[str] = field(default_factory=list)
	model_used: str = ""


@dataclass
class OrchestrationResult:
	plan_id: str
	query: str
	step_results: list[StepResult]
	final_output: str
	success: bool
	total_retries: int = 0
	error: str | None = None
	total_tokens: int = 0
	completed_message: str = ""
	artifact_dir: str = ""  # Fontes reais validados, inclusive recursos binários.
	# Contrato estruturado da entrega agentica. Evita serializar arquivos em
	# Markdown e reextrair exemplos de documentacao como module_N.py.
	artifact_files: list[str] = field(default_factory=list)
	# Pedido de entrega capturado na fronteira da UI e propagado ate o resultado.
	# Nao depende de uma flag mutavel sobreviver durante uma execucao longa.
	package_requested: bool = False
	package_path: str = ""
	# Trajeto completo do gateway Studio, incluindo tentativas e motivo da rota.
	routing_decisions: list[dict] = field(default_factory=list)
	selected_provider: str = ""
	selected_model: str = ""
