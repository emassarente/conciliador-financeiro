# =============================================================================
# MÓDULO RPA - DOMÍNIO WEB
# Responsável por fazer login automático no sistema Domínio,
# navegar até os relatórios e baixar o Razão contábil.
# Tecnologia: Python + Playwright
# =============================================================================

import os
import time
import logging
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# Configuração de logs para acompanhar o que o robô está fazendo
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


class DominioBot:
    """
    Robô RPA para o sistema Domínio Web.
    
    Este robô faz login, navega até o relatório de Razão contábil
    e baixa o arquivo para a pasta de dados.
    
    Como usar:
        bot = DominioBot(usuario="seu_usuario", senha="sua_senha")
        bot.executar(conta="1.1.1.01", data_ini="01/01/2024", data_fim="31/01/2024")
    """

    # URL base do sistema Domínio Web (ajuste conforme seu ambiente)
    URL_BASE = "https://dominioatendimento.com:443/dwsClient/"

    def __init__(self, usuario: str, senha: str, empresa: str = "",
                 pasta_download: str = None, headless: bool = False):
        """
        Inicializa o robô com as credenciais de acesso.
        
        Args:
            usuario:         Login do usuário no Domínio
            senha:           Senha do usuário
            empresa:         Código/nome da empresa (se necessário selecionar)
            pasta_download:  Onde salvar o arquivo baixado
            headless:        True = roda sem abrir janela do navegador
        """
        self.usuario = usuario
        self.senha = senha
        self.empresa = empresa
        self.headless = headless

        # Define a pasta de download padrão como data/samples dentro do projeto
        if pasta_download is None:
            base = Path(__file__).parent.parent
            self.pasta_download = str(base / "data" / "samples")
        else:
            self.pasta_download = pasta_download

        # Garante que a pasta existe
        os.makedirs(self.pasta_download, exist_ok=True)

        self.playwright = None
        self.browser = None
        self.page = None

    # -------------------------------------------------------------------------
    # MÉTODO PRINCIPAL
    # -------------------------------------------------------------------------
    def executar(self, conta: str, data_ini: str, data_fim: str) -> str:
        """
        Executa o fluxo completo: login → navegar → baixar razão.
        
        Args:
            conta:     Número da conta contábil (ex: "1.1.1.01")
            data_ini:  Data inicial no formato DD/MM/AAAA
            data_fim:  Data final no formato DD/MM/AAAA
            
        Returns:
            Caminho completo do arquivo baixado
        """
        logger.info("🤖 Iniciando robô Domínio...")
        arquivo_baixado = None

        with sync_playwright() as pw:
            self.playwright = pw
            self._abrir_navegador()
            try:
                self._fazer_login()
                self._selecionar_empresa()
                self._navegar_para_razao()
                arquivo_baixado = self._baixar_razao(conta, data_ini, data_fim)
                logger.info(f"✅ Arquivo baixado com sucesso: {arquivo_baixado}")
            except Exception as e:
                logger.error(f"❌ Erro durante execução: {e}")
                self._capturar_screenshot("erro_execucao")
                raise
            finally:
                self._fechar_navegador()

        return arquivo_baixado

    # -------------------------------------------------------------------------
    # NAVEGADOR
    # -------------------------------------------------------------------------
    def _abrir_navegador(self):
        """Abre o navegador Chrome/Chromium com configurações de download."""
        logger.info("🌐 Abrindo navegador...")
        self.browser = self.playwright.chromium.launch(
            headless=self.headless,
            downloads_path=self.pasta_download,
            args=["--start-maximized"]
        )
        # Contexto com idioma PT-BR e pasta de download configurada
        context = self.browser.new_context(
            accept_downloads=True,
            locale="pt-BR",
            viewport={"width": 1366, "height": 768}
        )
        self.page = context.new_page()
        self.page.set_default_timeout(30000)  # 30 segundos de timeout padrão

    def _fechar_navegador(self):
        """Fecha o navegador ao terminar."""
        if self.browser:
            self.browser.close()
            logger.info("🔒 Navegador fechado.")

    # -------------------------------------------------------------------------
    # LOGIN
    # -------------------------------------------------------------------------
    def _fazer_login(self):
        """Acessa a URL do Domínio e realiza o login."""
        logger.info(f"🔑 Fazendo login como '{self.usuario}'...")
        self.page.goto(self.URL_BASE)
        self.page.wait_for_load_state("networkidle")

        # Preenche usuário e senha — ajuste os seletores conforme o HTML do Domínio
        self.page.fill("input[name='usuario'], #usuario, input[placeholder*='usuário' i]", self.usuario)
        self.page.fill("input[name='senha'], #senha, input[type='password']", self.senha)
        self.page.click("button[type='submit'], input[type='submit'], #btnLogin, button:has-text('Entrar')")

        # Aguarda a página carregar após o login
        self.page.wait_for_load_state("networkidle")
        time.sleep(2)
        logger.info("✅ Login realizado.")

    def _selecionar_empresa(self):
        """Seleciona a empresa, se houver seleção de empresa na tela."""
        if not self.empresa:
            return  # Não foi informada empresa, pula esta etapa

        logger.info(f"🏢 Selecionando empresa: {self.empresa}...")
        try:
            # Tenta localizar campo ou select de empresa
            campo_empresa = self.page.locator(
                "input[name='empresa'], select[name='empresa'], #empresa, input[placeholder*='empresa' i]"
            ).first
            campo_empresa.fill(self.empresa)
            self.page.keyboard.press("Enter")
            time.sleep(1)
        except PlaywrightTimeout:
            logger.warning("⚠️ Campo de empresa não encontrado. Continuando sem selecionar.")

    # -------------------------------------------------------------------------
    # NAVEGAÇÃO ATÉ O RAZÃO
    # -------------------------------------------------------------------------
    def _navegar_para_razao(self):
        """
        Navega pelo menu do Domínio até chegar no relatório de Razão.
        
        ⚠️  IMPORTANTE: Os seletores abaixo são exemplos.
        Você DEVE inspecionar o HTML do seu Domínio Web e ajustar
        os seletores (texto do menu, IDs, classes) conforme necessário.
        """
        logger.info("📂 Navegando para Relatórios > Razão...")

        # Clica no menu "Relatórios" (ou "Contabilidade")
        self._clicar_com_retry(
            "text=Relatórios, text=Contabilidade, a:has-text('Relatório')",
            descricao="Menu Relatórios"
        )
        time.sleep(1)

        # Clica no submenu "Razão" (ou "Razão Contábil")
        self._clicar_com_retry(
            "text=Razão, a:has-text('Razão'), li:has-text('Razão')",
            descricao="Submenu Razão"
        )
        time.sleep(1)
        logger.info("✅ Tela de Razão aberta.")

    # -------------------------------------------------------------------------
    # DOWNLOAD DO RAZÃO
    # -------------------------------------------------------------------------
    def _baixar_razao(self, conta: str, data_ini: str, data_fim: str) -> str:
        """
        Preenche os filtros do relatório e baixa o arquivo Excel/CSV.
        
        Args:
            conta:    Conta contábil
            data_ini: Data inicial
            data_fim: Data final
            
        Returns:
            Caminho do arquivo baixado
        """
        logger.info(f"📋 Configurando filtros: conta={conta}, período={data_ini} a {data_fim}")

        # Preenche a conta contábil
        self._preencher_campo(
            "input[name='conta'], #conta, input[placeholder*='conta' i]",
            conta, "Conta contábil"
        )

        # Preenche a data inicial
        self._preencher_campo(
            "input[name='dataInicial'], #dataIni, input[placeholder*='inicial' i]",
            data_ini, "Data inicial"
        )

        # Preenche a data final
        self._preencher_campo(
            "input[name='dataFinal'], #dataFim, input[placeholder*='final' i]",
            data_fim, "Data final"
        )

        # Clica em "Gerar" ou "Pesquisar"
        self._clicar_com_retry(
            "button:has-text('Gerar'), button:has-text('Pesquisar'), input[value='Gerar']",
            descricao="Botão Gerar"
        )
        time.sleep(3)

        # Aguarda o relatório aparecer e clica em exportar para Excel
        logger.info("📥 Exportando para Excel...")
        with self.page.expect_download() as download_info:
            self._clicar_com_retry(
                "button:has-text('Excel'), a:has-text('Excel'), img[title*='Excel' i], button:has-text('Exportar')",
                descricao="Botão Exportar Excel"
            )
        download = download_info.value

        # Salva o arquivo com nome padronizado
        nome_arquivo = f"razao_{conta.replace('.', '_')}_{data_ini.replace('/', '')}_{data_fim.replace('/', '')}.xlsx"
        caminho_final = os.path.join(self.pasta_download, nome_arquivo)
        download.save_as(caminho_final)
        logger.info(f"💾 Arquivo salvo em: {caminho_final}")
        return caminho_final

    # -------------------------------------------------------------------------
    # UTILITÁRIOS INTERNOS
    # -------------------------------------------------------------------------
    def _clicar_com_retry(self, seletor: str, descricao: str = "", tentativas: int = 3):
        """
        Tenta clicar em um elemento, testando múltiplos seletores separados por vírgula.
        Útil quando não sabemos exatamente qual seletor o Domínio usa.
        """
        seletores = [s.strip() for s in seletor.split(",")]
        for tentativa in range(tentativas):
            for sel in seletores:
                try:
                    elemento = self.page.locator(sel).first
                    elemento.wait_for(state="visible", timeout=5000)
                    elemento.click()
                    logger.debug(f"✅ Clicou em '{descricao}' com seletor: {sel}")
                    return
                except Exception:
                    continue
            logger.warning(f"⚠️ Tentativa {tentativa + 1}/{tentativas} falhou para '{descricao}'")
            time.sleep(2)
        raise Exception(f"❌ Não foi possível clicar em '{descricao}' após {tentativas} tentativas.")

    def _preencher_campo(self, seletor: str, valor: str, descricao: str = ""):
        """Preenche um campo de texto, testando múltiplos seletores."""
        seletores = [s.strip() for s in seletor.split(",")]
        for sel in seletores:
            try:
                campo = self.page.locator(sel).first
                campo.wait_for(state="visible", timeout=5000)
                campo.clear()
                campo.fill(valor)
                logger.debug(f"✅ Preencheu '{descricao}' com '{valor}'")
                return
            except Exception:
                continue
        raise Exception(f"❌ Campo '{descricao}' não encontrado.")

    def _capturar_screenshot(self, nome: str):
        """Salva uma captura de tela para diagnóstico de erros."""
        if self.page:
            caminho = os.path.join(self.pasta_download, f"screenshot_{nome}.png")
            self.page.screenshot(path=caminho)
            logger.info(f"📸 Screenshot salvo: {caminho}")


# =============================================================================
# EXECUÇÃO DIRETA (para testar o bot isoladamente)
# =============================================================================
if __name__ == "__main__":
    # ⚠️ Substitua com suas credenciais reais antes de executar
    bot = DominioBot(
        usuario="SEU_USUARIO",
        senha="SUA_SENHA",
        empresa="",       # Preencha se necessário
        headless=False    # False = abre o navegador para você acompanhar
    )

    arquivo = bot.executar(
        conta="1.1.1.01",          # Conta bancária no plano de contas
        data_ini="01/01/2024",
        data_fim="31/01/2024"
    )
    print(f"\n✅ Arquivo baixado: {arquivo}")
