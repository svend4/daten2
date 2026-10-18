/**
 * Узел n8n для NPP-Act — вызов объявленного глагола через рантайм-шлюз.
 *
 * ЧЕСТНОЕ ПРЕДУПРЕЖДЕНИЕ, которое важнее любой строки кода ниже.
 * Этот узел САМ ПО СЕБЕ НЕ ЯВЛЯЕТСЯ ГАРАНТИЕЙ БЕЗОПАСНОСТИ. Узел — это поле
 * ввода в редакторе: любой, кто может править workflow, может сменить в нём
 * галочку. Удержание живёт не здесь, а в рантайме NPP-Act: губернатор решает
 * допуск до исполнения, журнал пишет персистентную хэш-цепь. Поэтому узел не
 * имеет и не должен иметь собственного HTTP-клиента к сервисам: он умеет
 * ровно одно — попросить рантайм (`POST /act/perform`) и показать его решение.
 *
 * Разделение ролей (SPEC-NPP-ACT.md §9):
 *   Наутилус   — каталог:      что существует;
 *   NPP-Act    — последствие:  что будет, если вызвать;
 *   n8n        — исполнение:   как вызвать и связать в цепочку;
 *   губернатор — удержание:    вправе ли агент это вызывать.
 * n8n не заменяет губернатора и не отменяет его. Узел, который «для скорости»
 * ходит в сервис напрямую, выключает четвёртую строку таблицы целиком.
 *
 * CommonJS, без зависимостей: единственный внешний импорт — типы ошибок
 * n8n-workflow, и он сделан мягко (см. loadNodeOperationError) ради того, чтобы
 * файл можно было загрузить и проверить вне установленного n8n.
 */

'use strict';

/**
 * n8n-workflow есть в рантайме n8n и может отсутствовать в тесте.
 * Терять из-за этого возможность загрузить файл не стоит: ошибка остаётся
 * ошибкой и без специального класса.
 */
function loadNodeOperationError() {
	try {
		// eslint-disable-next-line global-require
		return require('n8n-workflow').NodeOperationError;
	} catch (e) {
		return null;
	}
}

const NodeOperationError = loadNodeOperationError();

/** Эндпоинты рантайма. Других адресов узел не знает принципиально. */
const PERFORM = '/act/perform';
const CATALOG = '/act/catalog';
const HEALTH = '/api/health';
/** Маркер рантайма в ответе /api/health: у обычного сервиса его нет. */
const RUNTIME_MARKER = 'npp-act';

function fail(ctx, message, itemIndex) {
	if (NodeOperationError && ctx && typeof ctx.getNode === 'function') {
		return new NodeOperationError(ctx.getNode(), message, { itemIndex });
	}
	return new Error(message);
}

function trimUrl(value) {
	return String(value || '').trim().replace(/\/+$/, '');
}

/** Разобрать поле типа json: в n8n оно приходит и строкой, и уже объектом. */
function asObject(ctx, value, field, itemIndex) {
	if (value === undefined || value === null || value === '') return {};
	if (typeof value === 'object') return value;
	try {
		const parsed = JSON.parse(String(value));
		if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
			throw new Error('ожидался объект JSON');
		}
		return parsed;
	} catch (e) {
		throw fail(ctx, `поле «${field}» не является объектом JSON: ${e.message}`, itemIndex);
	}
}

/**
 * Один HTTP-запрос к рантайму.
 *
 * Отказ губернатора — это НЕ ошибка транспорта: шлюз отвечает 200 и телом с
 * verdict. Поэтому код различает «шлюз не ответил» и «шлюз ответил отказом»:
 * второе обязано дойти до выходного элемента, иначе workflow не сможет
 * ветвиться по решению и человек не узнает, что именно было запрещено.
 */
async function request(ctx, options, itemIndex) {
	const request_ = {
		json: true,
		returnFullResponse: true,
		ignoreHttpStatusErrors: true,
		...options,
	};
	let response;
	try {
		response = await ctx.helpers.httpRequest(request_);
	} catch (e) {
		const fromError = e && e.response ? e.response : null;
		if (fromError && fromError.body !== undefined) {
			response = fromError;
		} else {
			throw fail(ctx, `рантайм NPP-Act недоступен (${options.url}): ${e.message}`, itemIndex);
		}
	}
	const status = response && typeof response.statusCode === 'number' ? response.statusCode : 200;
	const body = response && response.body !== undefined ? response.body : response;
	return { status, body };
}

/** Проверить, что по адресу действительно рантайм, а не сам сервис. */
async function assertRuntime(ctx, gatewayUrl, itemIndex) {
	const { status, body } = await request(ctx, { method: 'GET', url: gatewayUrl + HEALTH }, itemIndex);
	const runtime = body && typeof body === 'object' ? body.runtime : undefined;
	if (status !== 200 || runtime !== RUNTIME_MARKER) {
		throw fail(
			ctx,
			`по адресу ${gatewayUrl} не рантайм NPP-Act (${HEALTH} вернул runtime=${JSON.stringify(runtime)}). ` +
				'Узел обязан ходить через рантайм: прямой вызов сервиса обходит губернатора и журнал.',
			itemIndex,
		);
	}
	return body;
}

/**
 * Проверить ответ /act/perform и отдать его дальше только если он годен.
 *
 * Штатный ответ — 200 с полем decision, включая отказ губернатора (block/escalate):
 * это решение, по нему workflow ветвится. Всё остальное — ошибка шлюза: 404 на
 * неверном пути, 502 при недоступном сервисе, 5xx. Такой ответ обязан стать
 * ошибкой узла. Иначе verdict становится «unknown», а узел молча выдаёт успех:
 * workflow принимает отсутствие решения за решение.
 */
function gatewayAnswer(ctx, status, answer, url, itemIndex) {
	if (status !== 200) {
		const detail = answer && typeof answer === 'object' && answer.error
			? answer.error
			: JSON.stringify(answer);
		throw fail(ctx, `рантайм NPP-Act ответил ${status} на ${url}: ${detail}`, itemIndex);
	}
	if (!answer || typeof answer !== 'object' || !answer.decision) {
		throw fail(ctx, `рантайм NPP-Act ответил без решения губернатора (${url})`, itemIndex);
	}
	return answer;
}

/**
 * Прочитать параметр узла.
 *
 * У контекста исполнения и у контекста выпадающих списков разные подписи
 * getNodeParameter: в первом вторым аргументом идёт индекс элемента, во втором
 * сразу значение по умолчанию. Поэтому itemIndex=null означает «мы в
 * loadOptions», и индекс передавать нельзя — иначе он будет понят как default.
 */
function param(ctx, name, itemIndex, fallback) {
	return itemIndex === null
		? ctx.getNodeParameter(name, fallback)
		: ctx.getNodeParameter(name, itemIndex, fallback);
}

/** Строки каталога из рантайма либо из манифеста сервиса. */
async function fetchCatalog(ctx, itemIndex) {
	const source = param(ctx, 'catalogSource', itemIndex, 'gateway');
	if (source === 'manifest') {
		const url = trimUrl(param(ctx, 'manifestUrl', itemIndex, ''));
		if (!url) throw fail(ctx, 'не указан URL манифеста (`/.well-known/npp-act.json`)', itemIndex);
		const { body } = await request(ctx, { method: 'GET', url }, itemIndex);
		if (!body || body.npp_act !== '1.0' || !Array.isArray(body.capabilities)) {
			throw fail(ctx, `${url} не похож на манифест NPP-Act 1.0`, itemIndex);
		}
		return body.capabilities.map((cap) => ({
			service: body.service,
			profile: body.profile,
			verb: cap.id,
			title: cap.title,
			effect: cap.effect,
			reversible: Boolean(cap.reversible),
			consent: cap.consent,
			idempotency: cap.idempotency || 'none',
			money: cap.cost ? cap.cost.money : undefined,
		}));
	}
	const gatewayUrl = trimUrl(param(ctx, 'gatewayUrl', itemIndex, ''));
	if (!gatewayUrl) throw fail(ctx, 'не указан адрес рантайм-шлюза NPP-Act', itemIndex);
	const { body } = await request(ctx, { method: 'GET', url: gatewayUrl + CATALOG }, itemIndex);
	if (!Array.isArray(body)) {
		throw fail(ctx, `${gatewayUrl}${CATALOG} вернул не список операций`, itemIndex);
	}
	return body;
}

class NppAct {
	constructor() {
		this.description = {
			displayName: 'NPP-Act',
			name: 'nppAct',
			// Иконка шрифтом, чтобы пакет не тащил бинарных файлов.
			icon: 'fa:gavel',
			group: ['transform'],
			version: 1,
			subtitle: '={{$parameter["service"] + ":" + $parameter["verb"]}}',
			description:
				'Вызов объявленного глагола NPP-Act через рантайм-шлюз: ' +
				'решение губернатора до исполнения, запись в журнал после',
			defaults: { name: 'NPP-Act' },
			inputs: ['main'],
			outputs: ['main'],
			properties: [
				{
					displayName: 'Операция',
					name: 'operation',
					type: 'options',
					noDataExpression: true,
					default: 'perform',
					options: [
						{
							name: 'Выполнить глагол',
							value: 'perform',
							description: 'Намерение → решение губернатора → (если допущено) исполнение',
							action: 'Выполнить глагол',
						},
						{
							name: 'Прочитать каталог',
							value: 'catalog',
							description: 'Какие глаголы объявлены и какие у них последствия',
							action: 'Прочитать каталог',
						},
					],
				},
				{
					displayName: 'Адрес рантайм-шлюза',
					name: 'gatewayUrl',
					type: 'string',
					default: 'http://127.0.0.1:8200',
					required: true,
					placeholder: 'http://127.0.0.1:8200',
					description:
						'Корень рантайма NPP-Act. Это НЕ адрес сервиса: ' +
						'прямой вызов сервиса обходит губернатора и журнал',
				},
				{
					displayName: 'Источник каталога',
					name: 'catalogSource',
					type: 'options',
					default: 'gateway',
					options: [
						{ name: 'Реестр рантайма', value: 'gateway', description: 'GET /act/catalog' },
						{
							name: 'Манифест сервиса',
							value: 'manifest',
							description: 'GET /.well-known/npp-act.json — только чтение объявления',
						},
					],
					description: 'Откуда брать список глаголов. Исполнение всё равно идёт через рантайм',
				},
				{
					displayName: 'URL манифеста',
					name: 'manifestUrl',
					type: 'string',
					default: '',
					placeholder: 'http://127.0.0.1:8210/.well-known/npp-act.json',
					displayOptions: { show: { catalogSource: ['manifest'] } },
				},
				{
					displayName: 'Сервис',
					name: 'service',
					type: 'options',
					default: '',
					typeOptions: {
						loadOptionsMethod: 'getServices',
						loadOptionsDependsOn: ['gatewayUrl', 'catalogSource', 'manifestUrl'],
					},
					displayOptions: { show: { operation: ['perform'] } },
					description: 'Идентификатор Actionable-сервиса из реестра',
				},
				{
					displayName: 'Глагол',
					name: 'verb',
					type: 'options',
					default: '',
					typeOptions: {
						loadOptionsMethod: 'getVerbs',
						loadOptionsDependsOn: ['service', 'gatewayUrl', 'catalogSource', 'manifestUrl'],
					},
					displayOptions: { show: { operation: ['perform'] } },
					description: 'Название подписано последствием: read · reserve · commit · money · destroy',
				},
				{
					displayName: 'Параметры входа',
					name: 'payload',
					type: 'json',
					default: '{}',
					displayOptions: { show: { operation: ['perform'] } },
					description: 'Объект JSON по схеме input из манифеста глагола',
				},
				{
					displayName: 'Ключ идемпотентности',
					name: 'idempotencyKey',
					type: 'string',
					default: '',
					displayOptions: { show: { operation: ['perform'] } },
					description:
						'Обязателен для effect=commit и effect=money: без него губернатор откажет. ' +
						'Повтор с тем же ключом тоже будет отклонён — это и есть защита от второго обязательства',
				},
				{
					displayName: 'Удержание',
					name: 'hold',
					type: 'json',
					default: '{}',
					displayOptions: { show: { operation: ['perform'] } },
					description:
						'Результат парного reserve-глагола ({hold_id, expires_at}). ' +
						'Губернатор блокирует commit по истёкшему удержанию',
				},
				{
					displayName: 'Сухой прогон',
					name: 'dryRun',
					type: 'boolean',
					default: true,
					displayOptions: { show: { operation: ['perform'] } },
					description:
						'Включено: только показать решение губернатора, НЕ исполнять. ' +
						'По умолчанию включено сознательно — в редакторе дешевле узнать последствие, чем его получить',
				},
				{
					displayName: 'Спросить губернатора перед исполнением',
					name: 'preflight',
					type: 'boolean',
					default: true,
					displayOptions: { show: { operation: ['perform'], dryRun: [false] } },
					description:
						'Сначала сухой прогон; при отказе настоящий запрос не отправляется. ' +
						'Это удобство, а не гарантия: гарантию даёт губернатор в рантайме, который спросят всё равно',
				},
				{
					displayName: 'Проверить, что по адресу рантайм',
					name: 'verifyGateway',
					type: 'boolean',
					default: true,
					description:
						'GET /api/health должен вернуть runtime="npp-act". ' +
						'Защита от самой частой ошибки — указать адрес сервиса вместо адреса рантайма',
				},
				{
					displayName: 'Падать при отказе губернатора',
					name: 'failOnBlock',
					type: 'boolean',
					default: false,
					displayOptions: { show: { operation: ['perform'] } },
					description:
						'Выключено: решение block/escalate приходит в выходной элемент, и workflow ветвится сам. ' +
						'Включено: узел бросает ошибку',
				},
				{
					displayName: 'Таймаут, мс',
					name: 'timeoutMs',
					type: 'number',
					default: 30000,
					typeOptions: { minValue: 1000 },
				},
			],
		};

		// Выпадающие списки читают каталог последствий, а не список путей:
		// человек в редакторе должен видеть «commit», прежде чем выберет глагол.
		this.methods = {
			loadOptions: {
				async getServices() {
					const rows = await fetchCatalog(this, null);
					const seen = new Map();
					for (const row of rows) {
						if (!row || !row.service || seen.has(row.service)) continue;
						seen.set(row.service, {
							name: row.profile ? `${row.service} (${row.profile})` : row.service,
							value: row.service,
						});
					}
					return [...seen.values()].sort((a, b) => a.value.localeCompare(b.value));
				},
				async getVerbs() {
					const service = this.getCurrentNodeParameter('service');
					const rows = await fetchCatalog(this, null);
					return rows
						.filter((row) => row && (!service || row.service === service))
						.map((row) => {
							const marks = [row.effect];
							if (row.consent && row.consent !== 'none') marks.push(`consent:${row.consent}`);
							if (row.reversible) marks.push('обратим');
							return {
								name: `${row.verb} — ${marks.join(', ')}`,
								value: row.verb,
								description: row.title || '',
							};
						})
						.sort((a, b) => a.value.localeCompare(b.value));
				},
			},
		};
	}

	async execute() {
		const items = this.getInputData();
		const out = [];

		for (let i = 0; i < items.length; i++) {
			try {
				const operation = this.getNodeParameter('operation', i, 'perform');
				const gatewayUrl = trimUrl(this.getNodeParameter('gatewayUrl', i, ''));
				const timeout = Number(this.getNodeParameter('timeoutMs', i, 30000));
				const verify = Boolean(this.getNodeParameter('verifyGateway', i, true));

				if (operation === 'catalog') {
					const rows = await fetchCatalog(this, i);
					for (const row of rows) {
						out.push({ json: row, pairedItem: { item: i } });
					}
					continue;
				}

				const service = String(this.getNodeParameter('service', i, '')).trim();
				const verb = String(this.getNodeParameter('verb', i, '')).trim();
				if (!service || !verb) {
					throw fail(this, 'не выбраны сервис и глагол', i);
				}
				if (!gatewayUrl) {
					throw fail(this, 'не указан адрес рантайм-шлюза NPP-Act', i);
				}

				const payload = asObject(this, this.getNodeParameter('payload', i, {}), 'Параметры входа', i);
				const holdRaw = asObject(this, this.getNodeParameter('hold', i, {}), 'Удержание', i);
				const key = String(this.getNodeParameter('idempotencyKey', i, '')).trim();
				const dryRun = Boolean(this.getNodeParameter('dryRun', i, true));
				const failOnBlock = Boolean(this.getNodeParameter('failOnBlock', i, false));
				const preflight = dryRun ? false : Boolean(this.getNodeParameter('preflight', i, true));

				if (verify) await assertRuntime(this, gatewayUrl, i);

				const body = {
					service,
					verb,
					payload,
					idempotency_key: key || null,
					dry_run: dryRun,
				};
				if (Object.keys(holdRaw).length) body.hold = holdRaw;

				const url = gatewayUrl + PERFORM;
				const post = async (dry) => {
					const { status, body: answer } = await request(
						this, { method: 'POST', url, body: { ...body, dry_run: dry }, timeout }, i);
					return gatewayAnswer(this, status, answer, url, i);
				};

				// Сухой прогон: узел обязан только показать решение и ничего не исполнить.
				// Поэтому здесь нет никакой ветки «а если admit, то давай сразу и сделаем».
				if (dryRun) {
					const answer = await post(true);
					out.push({
						json: shape(service, verb, answer, { dryRun: true, stoppedBy: null }),
						pairedItem: { item: i },
					});
					continue;
				}

				if (preflight) {
					const probe = await post(true);
					const verdict = probe && probe.decision ? probe.decision.verdict : 'unknown';
					if (verdict !== 'admit') {
						const json = shape(service, verb, probe, { dryRun: false, stoppedBy: 'preflight' });
						if (failOnBlock) {
							throw fail(this, `губернатор отказал (${verdict}): ${json.reason}`, i);
						}
						out.push({ json, pairedItem: { item: i } });
						continue;
					}
				}

				const answer = await post(false);
				const json = shape(service, verb, answer, { dryRun: false, stoppedBy: null });
				if (failOnBlock && json.verdict !== 'admit') {
					throw fail(this, `губернатор отказал (${json.verdict}): ${json.reason}`, i);
				}
				out.push({ json, pairedItem: { item: i } });
			} catch (e) {
				if (this.continueOnFail && this.continueOnFail()) {
					out.push({ json: { error: e.message }, pairedItem: { item: i } });
					continue;
				}
				throw e;
			}
		}

		return [out];
	}
}

/**
 * Привести ответ шлюза к плоскому виду для ветвления в workflow.
 * Решение выносится наверх (`verdict`), потому что это главное, что узел
 * сообщает миру: не «данные», а «было ли это вправе случиться».
 */
function shape(service, verb, answer, meta) {
	const decision = (answer && answer.decision) || {};
	const result = answer && answer.result ? answer.result : null;
	return {
		service,
		verb,
		dry_run: Boolean(meta.dryRun),
		verdict: decision.verdict || 'unknown',
		reason: decision.reason || '',
		alternative: decision.alternative || null,
		checks: decision.checks || [],
		executed: Boolean(answer && answer.executed),
		stopped_by: meta.stoppedBy,
		budget_remaining: answer && answer.budget_remaining !== undefined ? answer.budget_remaining : null,
		result: result ? result.body : null,
		status: result ? result.status : null,
		ok: result ? Boolean(result.ok) : null,
	};
}

module.exports = { NppAct };
