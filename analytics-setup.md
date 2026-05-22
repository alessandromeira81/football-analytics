# Analytics Setup — Como ativar GA4 + Microsoft Clarity

As páginas públicas (landing, precos, como-funciona, historico) já têm snippets
de tracking prontos, mas **desativados**. Quando quiser ligar, siga:

## 1. Criar conta GA4 (5 min)

1. https://analytics.google.com → "Comece a medir"
2. Crie uma propriedade "Estatísticas Pra Bet"
3. Tipo: Web / domínio: `estatisticasparabet.vercel.app` (ou seu domínio próprio depois)
4. Copie o **Measurement ID** (formato: `G-XXXXXXXXXX`)

## 2. Criar conta Microsoft Clarity (3 min)

1. https://clarity.microsoft.com → "Sign in" (use a mesma conta MS / GitHub)
2. "+ New project" → nome "Estatísticas Pra Bet"
3. Cole a URL do site
4. Copie o **Project ID** (10 chars alfanuméricos)

## 3. Ativar nos arquivos HTML

Em cada um destes arquivos, **descomente o bloco** `<!-- ANALYTICS -->` e substitua:
- `G-XXXXXXXXXX` → seu Measurement ID do GA4
- `XXXXXXXXXX` (no Clarity) → seu Project ID

**Arquivos a editar:**
- `landing.html`
- `precos.html`
- `como-funciona.html`
- `historico.html`

Exemplo (antes):
```html
<!--
<script async src="https://www.googletagmanager.com/gtag/js?id=G-XXXXXXXXXX"></script>
...
-->
```

Depois (descomentado + ID preenchido):
```html
<script async src="https://www.googletagmanager.com/gtag/js?id=G-7K2A8B3C1D"></script>
...
```

## 4. Commit + push

```bash
git add *.html
git commit -m "feat: ativa analytics GA4 + Clarity"
git push
```

Vercel rebuilda em ~1 min. Dados começam a aparecer nas plataformas em ~24h.

## 5. Métricas-chave a monitorar

### GA4
- **Aquisição → Visão geral** — de onde vem o tráfego
- **Engajamento → Páginas** — quais páginas convertem
- **Eventos** — `click` em "Acessar dashboard", "Avise-me", etc

### Clarity
- **Heatmaps** — onde clicam (e onde não clicam)
- **Session recordings** — assistir 10 sessões reais por semana
- **Dead clicks** — onde tentam clicar mas nada acontece
- **Rage clicks** — frustração detectada

## 6. Eventos customizados sugeridos (futuro)

Quando quiser tracking mais avançado, adicione na landing:

```javascript
// Botão de waitlist
function notifyMe(tier) {
  gtag('event', 'waitlist_signup', { plan: tier });
  // ...resto do código atual
}

// Click no CTA principal
document.querySelectorAll('a[href="/app"]').forEach(el => {
  el.addEventListener('click', () => {
    gtag('event', 'cta_click', { location: 'landing' });
  });
});
```
