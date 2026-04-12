import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { Type } from "@sinclair/typebox";

const BASE_URL = `http://127.0.0.1:${process.env.RT_SEARCH_PORT ?? "0"}`;

export default function webSearchExtension(pi: ExtensionAPI) {
	pi.registerTool({
		name: "web_search",
		label: "Web Search",
		description: "Search the web for information on a topic and return relevant results",
		promptSnippet: "Search the web and return relevant results for a query",
		parameters: Type.Object({
			query: Type.String({ description: "Search query" }),
			max_results: Type.Optional(Type.Number({ description: "Max results to return (default 5)" })),
		}),
		async execute(_toolCallId, params, signal) {
			const url = `${BASE_URL}/search?q=${encodeURIComponent(params.query)}&max=${params.max_results ?? 5}`;
			const resp = await fetch(url, { signal: signal ?? undefined });
			const data = await resp.json();
			return {
				content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
				details: data,
			};
		},
	});

	pi.registerTool({
		name: "web_fetch",
		label: "Web Fetch",
		description: "Fetch the full content of a specific URL",
		promptSnippet: "Fetch and return the content of a URL",
		parameters: Type.Object({
			url: Type.String({ description: "URL to fetch" }),
		}),
		async execute(_toolCallId, params, signal) {
			const url = `${BASE_URL}/fetch?url=${encodeURIComponent(params.url)}`;
			const resp = await fetch(url, { signal: signal ?? undefined });
			const data = await resp.json();
			return {
				content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
				details: data,
			};
		},
	});
}
