# PDF assinado com e-CNPJ A1 e carimbo do tempo SERPRO

Esta ferramenta assina um único PDF com a chave privada local de um e-CNPJ A1,
produz um CMS incorporado com `/SubFilter /ETSI.CAdES.detached` e acrescenta um
`DocTimeStamp` RFC 3161 da ACT SERPRO em uma revisão incremental posterior. Ela
não altera o fluxo web, o banco de dados nem o PDF original.

O titular exibido pela assinatura é o titular constante no certificado e-CNPJ.
A ferramenta não atribui a assinatura empresarial a um usuário do Rúbrica.

## Preparação no Ubuntu Server

No repositório do backend, a execução recomendada usa a imagem de produção e não
exige uma instalação separada do Poetry no servidor:

```bash
cd ~/projects/rubrica/rubrica-back
sudo install -d -m 700 /etc/rubrica/secrets
sudo install -d -m 755 /etc/rubrica/policies
sudo install -d -m 700 -o "$USER" -g "$USER" /srv/rubrica-ecnpj
```

Transfira o `.pfx`/`.p12`, o bundle confiável da ICP-Brasil e a política PAdES
vigente para o servidor por um canal seguro. Não use como raiz um certificado
retirado do próprio documento. A página oficial do ITI deve ser consultada para
confirmar a política vigente na data da assinatura.

```bash
sudo install -m 600 empresa.pfx /etc/rubrica/secrets/empresa-ecnpj-a1.pfx
sudo install -m 600 cadeia-icp-brasil.pem /etc/rubrica/secrets/icp-brasil-trust-roots.pem
sudo install -m 644 PA_PAdES_AD_RB_v1_3.der /etc/rubrica/policies/PA_PAdES_AD_RB_v1_3.der
sudo sh -c 'umask 077; cat > /etc/rubrica/secrets/empresa-ecnpj-a1.password'
```

No último comando, digite somente a senha e finalize com `Enter` e `Ctrl+D`.
O arquivo deve terminar com uma única quebra de linha, que a CLI remove. Para
reduzir a permanência da senha em disco, omita `ECNPJ_PFX_PASSWORD_FILE`: em um
terminal interativo, a CLI solicita a senha sem eco.

Crie um arquivo de ambiente fora do Git a partir de
`docs/ecnpj-signing.env.example`. A configuração da API Timestamp é a mesma já
usada pelo backend. O `Consumer Secret` continua em arquivo protegido.

## Assinar uma cópia de teste

Coloque o PDF original no diretório de operação e use o alvo do `makefile`:

```bash
sudo install -m 600 documento_teste.pdf /srv/rubrica-ecnpj/documento_teste.pdf
sudo make production-sign-ecnpj \
  input=documento_teste.pdf \
  output=documento_assinado.pdf
sudo chown "$USER:$USER" /srv/rubrica-ecnpj/documento_assinado.pdf
```

A saída é criada com modo exclusivo: se já existir, a ferramenta aborta. O PDF
original nunca é regravado. A chave privada é usada apenas localmente; para a
SERPRO segue somente a requisição RFC 3161 com o resumo criptográfico.

## O que a execução verifica

- certificado e chave do PKCS#12 utilizáveis;
- PAdES/CMS com SHA-256 e política de assinatura declarada;
- integridade criptográfica da assinatura;
- cadeia e revogação do certificado, usando as raízes configuradas;
- `DocTimeStamp` final, hash, nonce, política, cadeia, revogação e cobertura do
  arquivo inteiro;
- ausência de alterações posteriores ao carimbo.

A ferramenta incorpora informações de validação disponíveis na assinatura antes
de acrescentar o carimbo. Para isso, o servidor precisa acessar os endpoints de
CRL/OCSP indicados nos certificados e os endpoints da API Timestamp.

Essa verificação local não prova, sozinha, conformidade integral com todas as
extensões da política PAdES ICP-Brasil. O teste de aceitação final é baixar
`documento_assinado.pdf` e submetê-lo manualmente a
<https://validar.iti.gov.br/>. Um resultado aprovado deve identificar a pessoa
jurídica titular do e-CNPJ, a integridade da assinatura e o carimbo do tempo.

Não use certificado autoassinado como evidência de aceitação ICP-Brasil. Não
execute a ferramenta com o certificado real sem autorização expressa do titular.
