# Conversor de Vídeo para Áudio

Programa com janela para converter vídeos (MP4, MKV, AVI, MOV, WEBM e outros) em áudio (MP3, M4A, WAV, FLAC, OGG ou OPUS). Funciona offline depois da primeira execução.

## Recursos

- Converte vários arquivos de uma vez, ou uma pasta inteira
- Formatos de saída: MP3, M4A (AAC), WAV, FLAC, OGG (Vorbis) e OPUS
- Qualidade ajustável de 96 a 320 kbps (nos formatos com perda)
- Barra de progresso por arquivo e geral
- Botão de cancelar (o arquivo parcial é apagado)
- Arrastar e soltar arquivos ou pastas na janela
- Nunca sobrescreve: se `video.mp3` já existe, cria `video (1).mp3`
- Se um arquivo falha (sem áudio, corrompido), mostra o motivo na lista e continua com os outros

## Requisitos

- **Python 3.8 ou mais novo** ([python.org/downloads](https://www.python.org/downloads/)). No Windows, marque **"Add Python to PATH"** durante a instalação.
- Internet **apenas na primeira vez**, para baixar o FFmpeg (o motor de conversão) automaticamente.

Não precisa instalar o FFmpeg manualmente.

## Como usar

### Windows

1. Deixe `conversor.py` e `iniciar.bat` na mesma pasta.
2. Dê dois cliques em `iniciar.bat`. Na primeira vez ele instala o que falta e abre o programa.

### Linux / macOS

```bash
pip install imageio-ffmpeg tkinterdnd2
python3 conversor.py
```

No Linux, se aparecer o erro `No module named 'tkinter'`, instale com `sudo apt install python3-tk` (Debian/Ubuntu).

## Passo a passo

1. Clique em **Adicionar vídeos...** ou **Adicionar pasta...** (ou arraste os arquivos para a lista).
2. Escolha o **formato** e a **qualidade**.
3. Escolha onde salvar: na mesma pasta de cada vídeo, ou em outra pasta.
4. Clique em **Converter**.
5. Ao terminar, use **Abrir pasta de saída** para ver os arquivos.

## Qual formato escolher?

| Formato | Quando usar |
|---|---|
| MP3 | Compatível com tudo. A escolha padrão. |
| M4A | Boa qualidade em arquivos pequenos (iPhone, iTunes). |
| WAV / FLAC | Sem perda de qualidade. WAV é maior; FLAC é comprimido. |
| OGG / OPUS | Arquivos pequenos. OPUS é ótimo para voz. |

Dica: 192 kbps é um bom equilíbrio; 320 kbps é a qualidade máxima do MP3.

## Problemas comuns

| Mensagem | O que significa |
|---|---|
| Este arquivo não tem faixa de áudio | O vídeo é mudo, não há áudio para extrair. |
| Arquivo corrompido ou incompleto | O vídeo não foi baixado/copiado por inteiro. |
| Sem permissão para gravar na pasta de saída | Escolha outra pasta de saída. |
| FFmpeg não encontrado | Conecte à internet e abra de novo, ou rode `pip install imageio-ffmpeg`. Também funciona colocar o `ffmpeg.exe` na mesma pasta do programa. |
| Não dá para arrastar e soltar | Falta o `tkinterdnd2`. Abra pelo `iniciar.bat` ou rode `pip install tkinterdnd2`. |

## Arquivos

- `conversor.py`: o programa
- `iniciar.bat`: atalho para Windows que instala as dependências e abre o programa
