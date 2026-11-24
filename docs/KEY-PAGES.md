# KEY PAGES — where each credential comes from

Generated from `providers/providers.json` so it cannot drift from the registry.
**Nothing here is required for the agent to run.** The local tier (clawrouter, Ollama, vllm, llama.cpp, LM Studio) needs no key at all, and the whole test suite passes without one.

| Provider | env var | tier | probe answered | where the key is created | note |
|---|---|---|---|---|---|
| `opencode-zen` | `OPENCODE_ZEN_API_KEY` | free | yes | https://opencode.ai/auth | Sign in, then 'Create API Key' in the Console. **For a third-party client (this one) a key is not enough: free-tier chat models require the OpenCode client, so you need OpenCode Go (https://opencode.ai/go) or Console credits.** |
| `aihubmix` | `AIHUBMIX_API_KEY` | paid | yes | https://aihubmix.com/token | Aggregator; this is the gateway a stale container config pointed at. |
| `anthropic` | `ANTHROPIC_API_KEY` | paid | no | https://console.anthropic.com/settings/keys |  |
| `aws-bedrock` | `AWS_SECRET_ACCESS_KEY` | paid | no | https://console.aws.amazon.com/iam/home#/security_credentials | Needs AWS keys + region; SigV4, not OpenAI-compatible. |
| `azure-openai` | `AZURE_OPENAI_API_KEY` | paid | no | https://portal.azure.com/#view/Microsoft_Azure_ProjectOxford/CognitiveServicesHub | Needs a resource name substituted into base_url. |
| `cerebras` | `CEREBRAS_API_KEY` | paid | no | https://cloud.cerebras.ai/ | Account → API keys. |
| `deepseek` | `DEEPSEEK_API_KEY` | paid | no | https://platform.deepseek.com/api_keys |  |
| `fireworks` | `FIREWORKS_API_KEY` | paid | no | https://fireworks.ai/account/api-keys |  |
| `github-models` | `GITHUB_TOKEN` | paid | yes | https://github.com/settings/tokens/new?scopes=read:packages,models:read&description=zen-agent%20github%20models | Used for GitHub Models inference and for publishing to GitHub Packages. |
| `google-gemini` | `GEMINI_API_KEY` | paid | no | https://aistudio.google.com/app/apikey | Free tier available in AI Studio. |
| `google-vertex` | `GOOGLE_APPLICATION_CREDENTIALS` | paid | no | https://console.cloud.google.com/apis/credentials | Service account + region. |
| `groq` | `GROQ_API_KEY` | paid | no | https://console.groq.com/keys | Has a free tier. |
| `hyperbolic` | `HYPERBOLIC_API_KEY` | paid | no | https://app.hyperbolic.xyz/settings |  |
| `minimax` | `MINIMAX_API_KEY` | paid | no | https://platform.minimax.io/user-center/basic-information/interface-key |  |
| `mistral` | `MISTRAL_API_KEY` | paid | no | https://console.mistral.ai/api-keys/ | Has a free 'experiment' tier. |
| `moonshot-kimi` | `MOONSHOT_API_KEY` | paid | no | https://platform.moonshot.ai/console/api-keys |  |
| `nebius` | `NEBIUS_API_KEY` | paid | no | https://studio.nebius.com/settings/api-keys |  |
| `nous` | `NOUS_API_KEY` | paid | yes | https://portal.nousresearch.com/ | Portal → API keys. |
| `nvidia-nim` | `NVIDIA_API_KEY` | paid | yes | https://build.nvidia.com/settings/api-keys | Free credits on signup. |
| `openai` | `OPENAI_API_KEY` | paid | no | https://platform.openai.com/api-keys | Requires a funded org; the key alone is not enough. |
| `openrouter` | `OPENROUTER_API_KEY` | paid | no | https://openrouter.ai/settings/keys | Keys page (also: openrouter.ai/credits to add credit). |
| `perplexity` | `PERPLEXITY_API_KEY` | paid | no | https://www.perplexity.ai/settings/api | Needs credit on the account. |
| `sambanova` | `SAMBANOVA_API_KEY` | paid | yes | https://cloud.sambanova.ai/apis | Free tier on signup. |
| `siliconflow` | `SILICONFLOW_API_KEY` | paid | no | https://cloud.siliconflow.cn/account/ak |  |
| `together` | `TOGETHER_API_KEY` | paid | no | https://api.together.xyz/settings/api-keys |  |
| `xai` | `XAI_API_KEY` | paid | no | https://console.x.ai/team/default/api-keys |  |
| `zai-glm` | `ZAI_API_KEY` | paid | no | https://z.ai/manage-apikey/apikey-list |  |

## The two that actually unblock something

1. **Zen, and it is two purchases not one** — https://opencode.ai/auth creates the key, but a
   third-party client also needs **OpenCode Go** (https://opencode.ai/go) or Console credits. Measured:
   with a dummy key the API still answers `429 FreeUsageLimitError`, so the key is not the gate.
2. **A GitHub token with `write:packages`** — https://github.com/settings/tokens/new?scopes=write:packages,read:packages
   — only needed to publish the npm package to GitHub Packages. `gh auth token` from the existing
   device-flow login may already do it: check the scopes with `gh auth status`.

Everything else on this list is optional: it widens which capability can be routed where, and each
one is labelled `verified.reachable: false` in the registry until a live probe says otherwise.
