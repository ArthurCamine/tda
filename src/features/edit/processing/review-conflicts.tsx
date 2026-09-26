import { useState } from "react";
import { Button } from "@/components/ui/button";
import type { ReviewRebase } from "./review-rebase";
import styles from "./local-review.module.css";

export function ReviewConflicts({
	plan,
	onApply,
	onCancel,
}: Readonly<{
	plan: ReviewRebase;
	onApply: (choices: Readonly<Record<string, "local" | "remote">>) => void;
	onCancel: () => void;
}>) {
	const [choices, setChoices] = useState<Record<string, "local" | "remote">>(
		{},
	);
	const [page, setPage] = useState(0);
	const remaining = plan.collisions.length - Object.keys(choices).length;
	return (
		<section className={styles.notice} aria-label="Comparação da revisão">
			<p>
				{plan.localChanges} mudanças locais · {plan.collisions.length} colisões
				· {remaining} decisões pendentes.
			</p>
			<p>
				Alterações em campos diferentes serão combinadas. Nenhuma aprovação será
				herdada. Reconciliar mantém o draft não salvo.
			</p>
			{plan.collisions.slice(page * 25, page * 25 + 25).map((collision) => (
				<fieldset key={collision.id}>
					<legend>
						{collision.start === null
							? "Estado do draft"
							: `Fala em ${collision.start}s · ${collision.field}`}
					</legend>
					<label>
						<input
							type="radio"
							name={collision.id}
							checked={choices[collision.id] === "remote"}
							onChange={() =>
								setChoices((current) => ({
									...current,
									[collision.id]: "remote",
								}))
							}
						/>
						Usar versão mais recente
					</label>
					<pre className={styles.conflictText}>{String(collision.remote)}</pre>
					<label>
						<input
							type="radio"
							name={collision.id}
							checked={choices[collision.id] === "local"}
							onChange={() =>
								setChoices((current) => ({
									...current,
									[collision.id]: "local",
								}))
							}
						/>
						Manter minha alteração
					</label>
					<pre className={styles.conflictText}>{String(collision.local)}</pre>
				</fieldset>
			))}
			{plan.collisions.length > 25 ? (
				<div>
					<Button
						type="button"
						disabled={page === 0}
						onClick={() => setPage((value) => value - 1)}
					>
						Conflitos anteriores
					</Button>
					<Button
						type="button"
						disabled={(page + 1) * 25 >= plan.collisions.length}
						onClick={() => setPage((value) => value + 1)}
					>
						Próximos conflitos
					</Button>
				</div>
			) : null}
			<Button
				type="button"
				disabled={remaining > 0}
				onClick={() => onApply(choices)}
			>
				Reconciliar no draft
			</Button>
			<Button type="button" variant="tertiary" onClick={onCancel}>
				Cancelar comparação
			</Button>
		</section>
	);
}
